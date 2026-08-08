"""Tests for statement loading and dataframe selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pandas as pd
import pytest

from dollarby.data import Statement, StatementError, TransactionView, load_statement

if TYPE_CHECKING:
    from pathlib import Path

    from dollarby.processor import StatementProcessor


def test_statement_is_normalised(statement: Statement) -> None:
    """Normalise source rows, dates, and initial processing state."""
    assert list(statement.transactions["source_row"]) == [2, 3]
    assert pd.api.types.is_datetime64_any_dtype(statement.transactions["date"])
    assert statement.transactions.loc[0, "date"] == pd.Timestamp("2026-07-01")
    assert statement.unprocessed_count == len(statement.transactions)
    assert statement.processed_count == 0


def test_statement_rejects_unexpected_date_format(
    statement_path: Path,
    processor: StatementProcessor,
) -> None:
    """Reject dates which do not match the statement export contract."""
    source = statement_path.read_text(encoding="utf-8")
    statement_path.write_text(
        source.replace("01 Jul 26", "2026-07-01", 1),
        encoding="utf-8",
    )

    with pytest.raises(StatementError, match="contains invalid dates or amounts"):
        load_statement(statement_path, processor)


@pytest.mark.parametrize(
    ("placeholder", "value", "expected_tag"),
    [
        ("Example Merchant 1", "VODAFONE AU", "phone & internet"),
        ("Example purchase 1", "Starlink Internet", "phone & internet"),
        ("Example Merchant 1", "Spintel Pty Ltd", "phone & internet"),
        ("Example Merchant 1", "Liquor Barons Northbridge", "alcohol"),
        ("Example Merchant 1", "Liquorland 1234", "alcohol"),
        ("Example Merchant 1", "BWS 1234", "alcohol"),
    ],
)
def test_statement_tags_matching_words_in_the_configured_field(
    statement_path: Path,
    processor: StatementProcessor,
    value: str,
    expected_tag: str,
    placeholder: str,
) -> None:
    """Apply case-insensitive whole-word rules only to their configured field."""
    source = statement_path.read_text(encoding="utf-8")
    statement_path.write_text(source.replace(placeholder, value, 1), encoding="utf-8")

    statement = load_statement(statement_path, processor)
    tags = cast("frozenset[str]", statement.transactions.loc[0, "tags"])

    assert expected_tag in tags


def test_statement_does_not_apply_rules_to_the_other_field(
    statement_path: Path,
    processor: StatementProcessor,
) -> None:
    """Avoid evaluating each expression against both transaction fields."""
    source = statement_path.read_text(encoding="utf-8")
    source = source.replace("Example Merchant 1", "Starlink Internet", 1)
    source = source.replace("Example purchase 1", "Vodafone AU", 1)
    statement_path.write_text(source, encoding="utf-8")

    statement = load_statement(statement_path, processor)
    tags = cast("frozenset[str]", statement.transactions.loc[0, "tags"])

    assert tags == frozenset()


@pytest.mark.parametrize(
    "merchant_name",
    ["Grill'd", "BamBamBoo", "Jaws Sushi"],
)
def test_statement_applies_multiple_tags_from_one_rule(
    statement_path: Path,
    processor: StatementProcessor,
    merchant_name: str,
) -> None:
    """Add every tag listed by one matching rule."""
    source = statement_path.read_text(encoding="utf-8")
    source = source.replace("Example Merchant 1", merchant_name, 1)
    statement_path.write_text(source, encoding="utf-8")

    statement = load_statement(statement_path, processor)
    tags = cast("frozenset[str]", statement.transactions.loc[0, "tags"])

    assert tags == frozenset({"food", "restaurant"})


def test_final_rule_stops_later_tag_processing(
    statement_path: Path,
    processor: StatementProcessor,
) -> None:
    """Stop processing a row after a final rule while respecting word boundaries."""
    source = statement_path.read_text(encoding="utf-8")
    source = source.replace("Example Merchant 1", "Grill'd Liquorland", 1)
    source = source.replace("Example purchase 1", "Starlink Internet", 1)
    source = source.replace("Example Merchant 2", "Vodafonex BWS2", 1)
    source = source.replace("Example purchase 2", "notstarlink", 1)
    statement_path.write_text(source, encoding="utf-8")

    statement = load_statement(statement_path, processor)
    first_tags = cast("frozenset[str]", statement.transactions.loc[0, "tags"])
    second_tags = cast("frozenset[str]", statement.transactions.loc[1, "tags"])

    assert first_tags == frozenset({"food", "restaurant"})
    assert second_tags == frozenset()


def test_miscellaneous_tag_counts_as_processed(statement: Statement) -> None:
    """Treat any acknowledged tag as sufficient to leave the unprocessed view."""
    tags = [frozenset({"miscellaneous"})]
    tags.extend(frozenset[str]() for _ in range(len(statement.transactions) - 1))
    transactions = statement.transactions.assign(
        tags=pd.Series(tags, index=statement.transactions.index, dtype="object"),
    )
    tagged_statement = Statement(path=statement.path, transactions=transactions)

    assert tagged_statement.processed_count == 1
    assert len(tagged_statement.select(TransactionView.UNPROCESSED)) == 1


@pytest.mark.parametrize(
    "view",
    list(TransactionView),
)
def test_statement_selects_processing_views(
    partly_processed_statement: Statement,
    view: TransactionView,
) -> None:
    """Select processed, unprocessed, and complete transaction views."""
    expected_count = (
        len(partly_processed_statement.transactions) if view is TransactionView.ALL else 1
    )
    assert len(partly_processed_statement.select(view)) == expected_count
