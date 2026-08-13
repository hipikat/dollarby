"""Shared pytest fixtures for synthetic Dollarby statements."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dollarby.data import Statement, load_statement
from dollarby.processor import DEFAULT_PROCESSOR_PATH, ProcessorDocument, StatementProcessor

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
def processor_document(tmp_path: Path) -> ProcessorDocument:
    """Return a writable temporary copy of the local statement processor."""
    path = tmp_path / "processor.yaml"
    path.write_text(DEFAULT_PROCESSOR_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return ProcessorDocument.load(path)


@pytest.fixture
def processor(processor_document: ProcessorDocument) -> StatementProcessor:
    """Return the validated processor from a writable test document."""
    return processor_document.processor


@pytest.fixture
def statement(statement_path: Path, processor: StatementProcessor) -> Statement:
    """Return a loaded statement whose transactions have no Dollarby tags."""
    return load_statement(statement_path, processor)


@pytest.fixture
def partly_processed_statement(
    statement_path: Path,
    processor: StatementProcessor,
) -> Statement:
    """Return a statement with one automatically tagged restaurant transaction."""
    source = statement_path.read_text(encoding="utf-8")
    statement_path.write_text(
        source.replace("Example Merchant 1", "Grill'd", 1),
        encoding="utf-8",
    )
    return load_statement(statement_path, processor)


@pytest.fixture
def multi_tagged_statement(
    statement_path: Path,
    processor: StatementProcessor,
) -> Statement:
    """Return transactions carrying three tags across two merchants."""
    source = statement_path.read_text(encoding="utf-8")
    source = source.replace("Example Merchant 1", "Grill'd", 1)
    source = source.replace("Example Merchant 2", "Vodafone", 1)
    statement_path.write_text(source, encoding="utf-8")
    return load_statement(statement_path, processor)


@pytest.fixture
def large_statement(tmp_path: Path, processor: StatementProcessor) -> Statement:
    """Return enough transactions to exercise page-based TUI movement."""
    path = _write_statement(
        tmp_path / "large-statement.csv",
        transaction_count=LARGE_TRANSACTION_COUNT,
    )
    return load_statement(path, processor)
