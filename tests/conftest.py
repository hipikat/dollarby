"""Shared pytest fixtures for synthetic Dollarby statements."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from dollarby.data import Statement, load_statement

if TYPE_CHECKING:
    from pathlib import Path

TRANSACTION_COUNT = 2
LARGE_TRANSACTION_COUNT = 100
STATEMENT_HEADER = (
    "Date,Amount,Account Number,,Transaction Type,Transaction Details,"
    "Balance,Category,Merchant Name,Processed On"
)


def _write_statement(path: Path, *, transaction_count: int) -> Path:
    """Write a synthetic statement containing ``transaction_count`` rows."""
    rows = [STATEMENT_HEADER]
    for index in range(transaction_count):
        day = index % 28 + 1
        rows.append(
            f"{day:02d} Jul 26,-{index + 1}.00,123456,,DEBIT,"
            f"Example purchase {index + 1},{1000 - index}.00,,"
            f"Example Merchant {index + 1},{day:02d} Jul 26",
        )

    path.write_text("\n".join((*rows, "")), encoding="utf-8")
    return path


@pytest.fixture
def statement_path(tmp_path: Path) -> Path:
    """Return the path to a small valid synthetic statement."""
    return _write_statement(
        tmp_path / "statement.csv",
        transaction_count=TRANSACTION_COUNT,
    )


@pytest.fixture
def statement(statement_path: Path) -> Statement:
    """Return a loaded statement whose transactions have no Dollarby tags."""
    return load_statement(statement_path)


@pytest.fixture
def categorised_statement(statement: Statement) -> Statement:
    """Return a statement with only its first transaction tagged."""
    tags = [frozenset({"business"})]
    tags.extend(frozenset[str]() for _ in range(len(statement.transactions) - 1))
    transactions = statement.transactions.assign(
        tags=pd.Series(tags, index=statement.transactions.index, dtype="object"),
    )
    return Statement(path=statement.path, transactions=transactions)


@pytest.fixture
def large_statement(tmp_path: Path) -> Statement:
    """Return enough transactions to exercise page-based TUI movement."""
    path = _write_statement(
        tmp_path / "large-statement.csv",
        transaction_count=LARGE_TRANSACTION_COUNT,
    )
    return load_statement(path)
