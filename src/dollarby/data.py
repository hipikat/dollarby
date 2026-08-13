"""Load statements into Dollarby's canonical transaction dataframe."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, cast

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path

    from dollarby.processor import StatementProcessor

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
    """Choose which processing state to display."""

    UNPROCESSED = "unprocessed"
    PROCESSED = "processed"
    ALL = "all"


@dataclass(slots=True)
class Statement:
    """A source statement and its normalised transactions."""

    path: Path
    transactions: pd.DataFrame

    @property
    def processed_mask(self) -> pd.Series[bool]:
        """Return a mask identifying transactions with at least one tag."""
        return self.transactions["tags"].map(bool)

    @property
    def processed_count(self) -> int:
        """Return the number of transactions with at least one tag."""
        return int(self.processed_mask.sum())

    @property
    def unprocessed_count(self) -> int:
        """Return the number of transactions which still need a tag."""
        return len(self.transactions) - self.processed_count

    @property
    def tags(self) -> tuple[str, ...]:
        """Return every transaction tag in case-insensitive alphabetical order."""
        tag_sets = cast("list[frozenset[str]]", self.transactions["tags"].tolist())
        tags = {tag for transaction_tags in tag_sets for tag in transaction_tags}
        return tuple(sorted(tags, key=lambda tag: (tag.casefold(), tag)))

    def select(self, view: TransactionView) -> pd.DataFrame:
        """Select transactions for a processing-state view."""
        if view is TransactionView.ALL:
            return self.transactions

        mask = self.processed_mask
        if view is TransactionView.UNPROCESSED:
            mask = ~mask
        return self.transactions.loc[mask]

    def select_tag(self, tag: str) -> pd.DataFrame:
        """Select transactions carrying one tag."""
        mask = self.transactions["tags"].map(
            lambda transaction_tags: tag in cast("frozenset[str]", transaction_tags),
        )
        return self.transactions.loc[mask]

    def reprocess(self, processor: StatementProcessor) -> int:
        """Recalculate all tags and return the number of rows whose tags changed."""
        if "tags" in self.transactions:
            previous = cast("list[frozenset[str]]", self.transactions["tags"].tolist())
        else:
            previous = [frozenset() for _ in range(len(self.transactions))]

        updated = _transaction_tags(self.transactions, processor)
        current = cast("list[frozenset[str]]", updated.tolist())
        self.transactions["tags"] = updated
        return sum(before != after for before, after in zip(previous, current, strict=True))


def load_statement(path: Path, processor: StatementProcessor) -> Statement:
    """Read and normalise a CSV statement.

    Args:
        path: CSV statement to load.
        processor: Description of the source export and its tagging rules.

    Returns:
        The source path and canonical transaction dataframe.

    Raises:
        StatementError: The file is unreadable or does not have the expected shape.
    """
    account_number_column = processor.source_column("account_number")
    try:
        source = pd.read_csv(path, dtype={account_number_column: "string"})
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as error:
        message = f"Could not read statement {path}: {error}"
        raise StatementError(message) from error

    column_map = processor.statement.columns
    source = source.drop(columns=list(processor.statement.ignored_columns), errors="ignore")
    missing_columns = column_map.keys() - source.columns
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        message = f"Statement {path} is missing required columns: {missing}"
        raise StatementError(message)

    # Rename and retain only Dollarby's canonical transaction columns.
    transactions = source.rename(columns=column_map).loc[
        :,
        list(column_map.values()),
    ]

    # Convert source strings to canonical analytical dtypes.
    try:
        for column in processor.statement.dates.columns:
            transactions[column] = pd.to_datetime(
                transactions[column],
                format=processor.statement.dates.format,
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

    # Add source references and infer tags from the processor's ordered rules.
    transactions.insert(0, "source_row", range(2, len(transactions) + 2))
    statement = Statement(path=path, transactions=transactions)
    statement.reprocess(processor)
    return statement


def _transaction_tags(
    transactions: pd.DataFrame,
    processor: StatementProcessor,
) -> pd.Series:
    """Apply ordered tag rules, skipping later rules after a final match."""
    tag_sets = [set[str]() for _ in range(len(transactions))]
    active_rows = [True for _ in range(len(transactions))]

    for column_rule in processor.tagging.rules:
        values = transactions[column_rule.column].tolist()
        for rule in column_rule.matches:
            pattern = rule.compile(case_sensitive=processor.tagging.case_sensitive)
            for position, value in enumerate(values):
                if not active_rows[position] or pattern.search(str(value)) is None:
                    continue

                tag_sets[position].update(rule.tags)
                if rule.final:
                    active_rows[position] = False

    return pd.Series(
        [frozenset(tags) for tags in tag_sets],
        index=transactions.index,
        dtype="object",
    )
