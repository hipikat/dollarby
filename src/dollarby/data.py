"""Load statements into Dollarby's canonical transaction dataframe."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_COLUMNS: Final = {
    "Date": "date",
    "Amount": "amount",
    "Account Number": "account_number",
    "Transaction Type": "transaction_type",
    "Transaction Details": "transaction_details",
    "Balance": "balance",
    "Category": "source_category",
    "Merchant Name": "merchant_name",
    "Processed On": "processed_on",
}

STATEMENT_DATE_FORMAT: Final = "%d %b %y"

TEXT_COLUMNS: Final = (
    "account_number",
    "transaction_type",
    "transaction_details",
    "source_category",
    "merchant_name",
)


class StatementError(ValueError):
    """Indicate that a statement could not be loaded safely."""


class TransactionView(StrEnum):
    """Choose which categorisation state to display."""

    UNCATEGORISED = "uncategorised"
    CATEGORISED = "categorised"
    ALL = "all"


@dataclass(slots=True)
class Statement:
    """A source statement and its normalised transactions."""

    path: Path
    transactions: pd.DataFrame

    @property
    def categorised_mask(self) -> pd.Series[bool]:
        """Return a mask identifying transactions with Dollarby tags."""
        return self.transactions["tags"].map(bool)

    @property
    def categorised_count(self) -> int:
        """Return the number of transactions with Dollarby tags."""
        return int(self.categorised_mask.sum())

    @property
    def uncategorised_count(self) -> int:
        """Return the number of transactions without Dollarby tags."""
        return len(self.transactions) - self.categorised_count

    def select(self, view: TransactionView) -> pd.DataFrame:
        """Select transactions for a categorisation-state view."""
        if view is TransactionView.ALL:
            return self.transactions

        mask = self.categorised_mask
        if view is TransactionView.UNCATEGORISED:
            mask = ~mask
        return self.transactions.loc[mask]


def load_statement(path: Path) -> Statement:
    """Read and normalise a CSV statement.

    Args:
        path: CSV statement to load.

    Returns:
        The source path and canonical transaction dataframe.

    Raises:
        StatementError: The file is unreadable or does not have the expected shape.
    """
    try:
        source = pd.read_csv(path, dtype={"Account Number": "string"})
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as error:
        message = f"Could not read statement {path}: {error}"
        raise StatementError(message) from error

    # Discard unnamed separator columns from the bank export.
    source = source.drop(columns=_unnamed_columns(source))
    missing_columns = SOURCE_COLUMNS.keys() - source.columns
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        message = f"Statement {path} is missing required columns: {missing}"
        raise StatementError(message)

    # Rename and retain only Dollarby's canonical transaction columns.
    transactions = source.rename(columns=SOURCE_COLUMNS).loc[:, list(SOURCE_COLUMNS.values())]

    # Convert source strings to canonical analytical dtypes.
    try:
        transactions["date"] = pd.to_datetime(
            transactions["date"],
            format=STATEMENT_DATE_FORMAT,
            errors="raise",
        )
        transactions["processed_on"] = pd.to_datetime(
            transactions["processed_on"],
            format=STATEMENT_DATE_FORMAT,
            errors="raise",
        )
        transactions["amount"] = pd.to_numeric(transactions["amount"], errors="raise")
        transactions["balance"] = pd.to_numeric(transactions["balance"], errors="raise")
    except (TypeError, ValueError) as error:
        message = f"Statement {path} contains invalid dates or amounts: {error}"
        raise StatementError(message) from error

    # Keep missing text values out of downstream filters and display.
    for column in TEXT_COLUMNS:
        transactions[column] = transactions[column].fillna("").astype("string")

    # Add source references and initially empty Dollarby tags.
    transactions.insert(0, "source_row", range(2, len(transactions) + 2))
    transactions = transactions.assign(
        tags=pd.Series(
            [frozenset[str]() for _ in range(len(transactions))],
            index=transactions.index,
            dtype="object",
        ),
    )

    return Statement(path=path, transactions=transactions)


def _unnamed_columns(frame: pd.DataFrame) -> list[str]:
    """Find empty CSV columns generated as ``Unnamed: n`` by pandas."""
    return [str(column) for column in frame.columns if str(column).startswith("Unnamed:")]
