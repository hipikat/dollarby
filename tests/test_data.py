"""Tests for statement loading and dataframe selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from dollarby.data import Statement, StatementError, TransactionView, load_statement

if TYPE_CHECKING:
    from pathlib import Path


def test_statement_is_normalised(statement: Statement) -> None:
    """Normalise source rows, dates, and initial categorisation state."""
    assert list(statement.transactions["source_row"]) == [2, 3]
    assert pd.api.types.is_datetime64_any_dtype(statement.transactions["date"])
    assert statement.transactions.loc[0, "date"] == pd.Timestamp("2026-07-01")
    assert statement.uncategorised_count == len(statement.transactions)


def test_statement_rejects_unexpected_date_format(statement_path: Path) -> None:
    """Reject dates which do not match the statement export contract."""
    source = statement_path.read_text(encoding="utf-8")
    statement_path.write_text(
        source.replace("01 Jul 26", "2026-07-01", 1),
        encoding="utf-8",
    )

    with pytest.raises(StatementError, match="contains invalid dates or amounts"):
        load_statement(statement_path)


@pytest.mark.parametrize(
    "view",
    list(TransactionView),
)
def test_statement_selects_categorisation_views(
    categorised_statement: Statement,
    view: TransactionView,
) -> None:
    """Select categorised, uncategorised, and complete transaction views."""
    expected_count = len(categorised_statement.transactions) if view is TransactionView.ALL else 1
    assert len(categorised_statement.select(view)) == expected_count
