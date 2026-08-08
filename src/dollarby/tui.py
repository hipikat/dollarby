"""Dollarby's interactive Textual application."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast, override

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Label, Select, Static

from dollarby.data import Statement, TransactionView

if TYPE_CHECKING:
    from datetime import datetime

VIEW_OPTIONS: tuple[tuple[str, TransactionView], ...] = (
    ("Uncategorised", TransactionView.UNCATEGORISED),
    ("Categorised", TransactionView.CATEGORISED),
    ("All", TransactionView.ALL),
)


class TransactionTable(DataTable[object]):
    """Display transactions with familiar Vim-style navigation."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("ctrl+f", "page_down", "Page down", show=False),
        Binding("ctrl+b", "page_up", "Page up", show=False),
        Binding("ctrl+d", "half_page_down", "Half-page down", show=False),
        Binding("ctrl+u", "half_page_up", "Half-page up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
    ]

    def action_half_page_down(self) -> None:
        """Move the cursor half a visible page down."""
        if self.row_count:
            target = min(self.cursor_row + self._half_page_rows(), self.row_count - 1)
            self.move_cursor(row=target)

    def action_half_page_up(self) -> None:
        """Move the cursor half a visible page up."""
        if self.row_count:
            target = max(self.cursor_row - self._half_page_rows(), 0)
            self.move_cursor(row=target)

    def _half_page_rows(self) -> int:
        """Return half the number of rows visible below the header."""
        content_height = self.scrollable_content_region.height
        if self.show_header:
            content_height -= self.header_height
        return max(content_height // 2, 1)


class DollarbyApp(App[None]):
    """Browse and, eventually, categorise transactions in one statement."""

    TITLE = "Dollarby"
    CSS = """
    Screen {
        layout: vertical;
    }

    #toolbar {
        height: 3;
        padding: 0 1;
        align: left middle;
    }

    #view-label {
        width: auto;
        margin-right: 1;
        content-align: left middle;
    }

    #transaction-view {
        width: 24;
    }

    #transactions {
        height: 1fr;
        border-top: solid $accent;
    }

    #summary {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
    ]

    def __init__(self, statement: Statement) -> None:
        """Create the transaction browser for one statement."""
        super().__init__()
        self.statement = statement
        self.sub_title = statement.path.name

    @override
    def compose(self) -> ComposeResult:
        """Compose the initial transaction-browser screen."""
        yield Header()
        with Horizontal(id="toolbar"):
            yield Label("Show", id="view-label")
            yield Select[TransactionView](
                VIEW_OPTIONS,
                value=TransactionView.UNCATEGORISED,
                allow_blank=False,
                compact=True,
                id="transaction-view",
            )
        yield TransactionTable(id="transactions", cursor_type="row", zebra_stripes=True)
        yield Static(id="summary")
        yield Footer()

    def on_mount(self) -> None:
        """Set up and populate the transaction table."""
        table = self.query_one("#transactions", TransactionTable)
        table.add_columns("", "Date", "Amount", "Merchant", "Details", "Type", "Tags")
        self._show_transactions(TransactionView.UNCATEGORISED)
        table.focus()

    @on(Select.Changed, "#transaction-view")
    def change_transaction_view(self, event: Select.Changed) -> None:
        """Replace the rows when the selected categorisation view changes."""
        if isinstance(event.value, TransactionView):
            self._show_transactions(event.value)

    def _show_transactions(self, view: TransactionView) -> None:
        """Populate the table with transactions from one view."""
        table = self.query_one("#transactions", TransactionTable)
        table.clear()

        selected = self.statement.select(view)
        for transaction in selected.itertuples(index=False):
            # pandas-stubs exposes each named tuple value as a broad union; the
            # statement loader establishes these concrete canonical dtypes.
            amount = float(cast("int | float", transaction.amount))
            date = cast("datetime", transaction.date)
            tags = sorted(cast("frozenset[str]", transaction.tags))
            table.add_row(
                _status(categorised=bool(tags)),
                date.strftime("%Y-%m-%d"),
                _amount(amount),
                str(transaction.merchant_name),
                str(transaction.transaction_details),
                str(transaction.transaction_type),
                ", ".join(tags),
                key=str(cast("int", transaction.source_row)),
            )

        summary = self.query_one("#summary", Static)
        summary.update(
            f"{len(selected):,} shown · "
            f"{self.statement.uncategorised_count:,} uncategorised · "
            f"{self.statement.categorised_count:,} categorised · "
            f"{len(self.statement.transactions):,} total",
        )


def run_tui(statement: Statement) -> None:
    """Run Dollarby's full-screen transaction browser."""
    DollarbyApp(statement).run()


def _status(*, categorised: bool) -> Text:
    """Render a transaction's categorisation status."""
    if categorised:
        return Text("✓", style="green")
    return Text("!", style="yellow")


def _amount(amount: float) -> Text:
    """Render an amount with sign-aware colour."""
    style = "green" if amount >= 0 else "red"
    return Text(f"${amount:,.2f}", style=style, justify="right")
