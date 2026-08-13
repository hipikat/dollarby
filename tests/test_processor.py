"""Tests for YAML statement processor configuration."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

from dollarby.processor import (
    DEFAULT_PROCESSOR_PATH,
    PROCESSOR_SCHEMA_VERSION,
    NewTagRule,
    ProcessorDocument,
    ProcessorError,
    TagRule,
    TagRuleField,
    load_processor,
)

if TYPE_CHECKING:
    from pathlib import Path

ATOMIC_REPLACE_FAILURE = "synthetic replacement failure"


def test_nab_processor_defines_export_and_match_order() -> None:
    """Load the initial NAB export contract from YAML."""
    processor = load_processor(DEFAULT_PROCESSOR_PATH)

    assert processor.schema_version == PROCESSOR_SCHEMA_VERSION
    assert processor.source_column("date") == "Date"
    assert processor.statement.dates.format == "%d %b %y"
    assert processor.tagging.hidden_tags == ("alcohol",)
    assert tuple(rule.column for rule in processor.tagging.rules) == (
        "merchant_name",
        "transaction_details",
    )
    restaurant_rule = processor.tagging.rules[0].matches[0]
    assert restaurant_rule.tags == ("food", "restaurant")
    assert restaurant_rule.final is True
    assert all(
        rule.final for column_rules in processor.tagging.rules for rule in column_rules.matches
    )
    assert tuple(rule.tags for rule in processor.tagging.rules[1].matches) == (
        ("personal",),
        ("transport",),
        ("rent",),
    )


def test_tag_rule_compiles_escaped_whole_literals() -> None:
    """Treat scalar and list values as literals with punctuation-safe word edges."""
    rule = TagRule(contains=("Grill'd", "A+B"), tags=("food",))
    pattern = rule.compile(case_sensitive=False)

    assert pattern.search("Lunch at GRILL'D") is not None
    assert pattern.search("Paid A+B today") is not None
    assert pattern.search("notGrill'd") is None
    assert pattern.search("A+Bonus") is None


def test_processor_rejects_empty_contains(tmp_path: Path) -> None:
    """Report empty literal lists as processor errors."""
    source = yaml.safe_load(DEFAULT_PROCESSOR_PATH.read_text(encoding="utf-8"))
    source["tagging"]["rules"][0]["matches"][0]["contains"] = []
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    with pytest.raises(ProcessorError, match="contains"):
        load_processor(path)


def test_processor_file_cannot_be_completed_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat a selected processor as a complete, reproducible document."""
    source = yaml.safe_load(DEFAULT_PROCESSOR_PATH.read_text(encoding="utf-8"))
    del source["name"]
    path = tmp_path / "missing-name.yaml"
    path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("name", "Environment override")

    with pytest.raises(ProcessorError, match="name"):
        load_processor(path)


def test_processor_document_persists_and_round_trips_rules(
    processor_document: ProcessorDocument,
) -> None:
    """Write canonical YAML which reloads to the same validated processor."""
    rule = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="Synthetic Merchant",
        tags=("Work",),
    )

    updated = processor_document.add_tag_rule(rule)
    reloaded = ProcessorDocument.load(processor_document.path)
    source = yaml.safe_load(processor_document.path.read_text(encoding="utf-8"))
    written_rule = source["tagging"]["rules"][0]["matches"][-1]

    assert reloaded.processor == updated
    assert written_rule == {"contains": "Synthetic Merchant", "tags": ["Work"]}


def test_processor_document_merges_tags_into_an_equivalent_rule(
    processor_document: ProcessorDocument,
) -> None:
    """Upsert equal case-insensitive literal sets without adding unreachable rules."""
    first = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="Synthetic Merchant",
        tags=("Work",),
    )
    second = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="synthetic merchant",
        tags=("Recurring", "work"),
    )
    initial_count = len(processor_document.processor.tagging.rules[0].matches)

    processor_document.add_tag_rule(first)
    updated = processor_document.add_tag_rule(second)
    written = updated.tagging.rules[0].matches[-1]

    assert len(updated.tagging.rules[0].matches) == initial_count + 1
    assert written.contains == "Synthetic Merchant"
    assert written.tags == ("Work", "Recurring")


def test_processor_document_merges_matches_with_an_equivalent_tag_set(
    processor_document: ProcessorDocument,
) -> None:
    """Collect same-column matches under one case-insensitively equal tag set."""
    first = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="Synthetic Merchant",
        tags=("Work", "Recurring"),
    )
    second = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="Another Merchant",
        tags=("recurring", "work"),
    )
    initial_count = len(processor_document.processor.tagging.rules[0].matches)

    processor_document.add_tag_rule(first)
    updated = processor_document.add_tag_rule(second)
    written = updated.tagging.rules[0].matches[-1]
    pattern = written.compile(case_sensitive=False)

    assert len(updated.tagging.rules[0].matches) == initial_count + 1
    assert written.contains == ("Synthetic Merchant", "Another Merchant")
    assert written.tags == ("Work", "Recurring")
    assert pattern.search("SYNTHETIC MERCHANT") is not None
    assert pattern.search("another merchant") is not None


def test_processor_document_refuses_to_overwrite_external_changes(
    processor_document: ProcessorDocument,
) -> None:
    """Protect edits made after Dollarby loaded the processor document."""
    source = processor_document.path.read_text(encoding="utf-8")
    processor_document.path.write_text(f"{source}\n", encoding="utf-8")
    rule = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="Synthetic Merchant",
        tags=("Work",),
    )

    with pytest.raises(ProcessorError, match="changed after Dollarby loaded"):
        processor_document.add_tag_rule(rule)


def test_processor_document_preserves_source_when_atomic_replace_fails(
    processor_document: ProcessorDocument,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the old document and model when the final atomic replacement fails."""
    source = processor_document.path.read_text(encoding="utf-8")
    original_processor = processor_document.processor
    rule = NewTagRule(
        field=TagRuleField.MERCHANT,
        contains="Synthetic Merchant",
        tags=("Work",),
    )

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError(ATOMIC_REPLACE_FAILURE)

    monkeypatch.setattr(type(processor_document.path), "replace", fail_replace)

    with pytest.raises(ProcessorError, match=re.escape(ATOMIC_REPLACE_FAILURE)):
        processor_document.add_tag_rule(rule)

    assert processor_document.path.read_text(encoding="utf-8") == source
    assert processor_document.processor == original_processor
    assert not tuple(processor_document.path.parent.glob(f".{processor_document.path.name}.*.tmp"))
