"""Tests for YAML statement processor configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dollarby.processor import (
    DEFAULT_PROCESSOR_PATH,
    PROCESSOR_SCHEMA_VERSION,
    ProcessorError,
    load_processor,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_nab_processor_defines_export_and_match_order() -> None:
    """Load the initial NAB export contract from YAML."""
    processor = load_processor(DEFAULT_PROCESSOR_PATH)

    assert processor.schema_version == PROCESSOR_SCHEMA_VERSION
    assert processor.source_column("date") == "Date"
    assert processor.statement.dates.format == "%d %b %y"
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


def test_processor_rejects_invalid_regex(tmp_path: Path) -> None:
    """Report malformed tag expressions as processor errors."""
    source = DEFAULT_PROCESSOR_PATH.read_text(encoding="utf-8")
    path = tmp_path / "invalid.yaml"
    path.write_text(
        source.replace("'\\b(?:vodafone|spintel)\\b'", "'['", 1),
        encoding="utf-8",
    )

    with pytest.raises(ProcessorError, match="invalid regex"):
        load_processor(path)


def test_processor_file_cannot_be_completed_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat a selected processor as a complete, reproducible document."""
    source = DEFAULT_PROCESSOR_PATH.read_text(encoding="utf-8")
    path = tmp_path / "missing-name.yaml"
    path.write_text(
        source.replace("name: NAB transaction export (2026)\n", "", 1),
        encoding="utf-8",
    )
    monkeypatch.setenv("name", "Environment override")

    with pytest.raises(ProcessorError, match="name"):
        load_processor(path)
