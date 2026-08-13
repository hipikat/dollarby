"""Dollarby's interactive Textual application."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast, override

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from dollarby.data import Statement, TagFilter, TagFilterError, TagFilterField, TransactionView

if TYPE_CHECKING:
    from datetime import datetime

    import pandas as pd

VIEW_OPTIONS: tuple[tuple[str, TransactionView], ...] = (
    ("Unprocessed", TransactionView.UNPROCESSED),
    ("Processed", TransactionView.PROCESSED),
    ("All", TransactionView.ALL),
)
TRANSACTION_COLUMNS: tuple[str, ...] = (
    "Tagged",
    "Date",
    "Amount",
    "Merchant",
    "Details",
    "Type",
    "Tags",
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


class TagList(ListView):
    """Display the statement's tags with Vim-style navigation."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, tags: tuple[str, ...], *, widget_id: str) -> None:
        """Create an alphabetical list of tags."""
        self.tags = tags
        items = (ListItem(Label(tag)) for tag in tags)
        super().__init__(
            *items,
            initial_index=0 if tags else None,
            id=widget_id,
        )

    @property
    def active_tag(self) -> str | None:
        """Return the highlighted tag, if the statement has any tags."""
        if self.index is None:
            return None
        return self.tags[self.index]

    async def replace_tags(self, tags: tuple[str, ...], *, active_tag: str) -> None:
        """Replace the available tags and highlight one requested tag."""
        self.index = None
        await self.clear()
        self.tags = tags
        await self.extend(ListItem(Label(tag)) for tag in tags)
        self.index = tags.index(active_tag) if active_tag in tags else 0 if tags else None


class AddTagFilterDialog(ModalScreen[TagFilter | None]):
    """Collect one field-specific tag filter without leaving the current view."""

    CSS = """
    AddTagFilterDialog {
        align: center middle;
    }

    #tag-filter-dialog {
        width: 80%;
        min-width: 60;
        max-width: 100;
        height: 22;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #filter-title {
        height: 1;
        text-style: bold;
        content-align: center middle;
    }

    #filter-help {
        height: 2;
        color: $text-muted;
        content-align: center middle;
    }

    #match-fields {
        height: 6;
        margin-top: 1;
    }

    #filter-field {
        width: 18;
        height: 6;
        border: none;
        padding: 0;
        background: $surface;
    }

    #filter-field RadioButton {
        width: 100%;
        height: 3;
    }

    #filter-matches {
        width: 1fr;
        height: 6;
    }

    #tags-row {
        height: 3;
        margin-top: 1;
    }

    #tags-label {
        width: 18;
        padding: 0 1;
        content-align: left middle;
    }

    #filter-tags {
        width: 1fr;
    }

    #filter-error {
        height: 1;
        color: $error;
    }

    #filter-buttons {
        height: 3;
        align: right middle;
    }

    #filter-buttons Button {
        width: 16;
        margin-left: 1;
    }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("ctrl+s", "save", "Save", show=False, priority=True),
    ]

    def __init__(self, *, merchant: str = "", details: str = "") -> None:
        """Create a dialog pre-filled from an optional selected transaction."""
        super().__init__()
        self.merchant = merchant
        self.details = details

    @override
    def compose(self) -> ComposeResult:
        """Compose the field, match-text, tag, and action controls."""
        with Vertical(id="tag-filter-dialog"):
            yield Label("Add Tag Filter", id="filter-title")
            yield Static(
                "Literal matching is case-insensitive. Filters apply to this session only.",
                id="filter-help",
            )
            with Horizontal(id="match-fields"):
                with RadioSet(id="filter-field"):
                    yield RadioButton("Merchant", value=True, id="filter-merchant")
                    yield RadioButton("Details", id="filter-details")
                with Vertical(id="filter-matches"):
                    yield Input(
                        self.merchant,
                        placeholder="Merchant text",
                        id="merchant-match",
                    )
                    yield Input(
                        self.details,
                        placeholder="Transaction details text",
                        id="details-match",
                    )
            with Horizontal(id="tags-row"):
                yield Label("Tags", id="tags-label")
                yield Input(
                    placeholder="Comma-separated tags",
                    id="filter-tags",
                )
            yield Static(id="filter-error")
            with Horizontal(id="filter-buttons"):
                yield Button("Cancel", id="cancel-filter")
                yield Button("Save", variant="primary", id="save-filter")

    def on_mount(self) -> None:
        """Put the cursor in the selected field's editable match text."""
        self.query_one("#merchant-match", Input).focus()

    @on(Button.Pressed)
    def press_button(self, event: Button.Pressed) -> None:
        """Save or cancel from the dialog buttons."""
        if event.button.id == "save-filter":
            self.action_save()
        else:
            self.action_cancel()

    @on(Input.Submitted, "#filter-tags")
    def submit_tags(self) -> None:
        """Save when Enter is pressed in the final text field."""
        self.action_save()

    def action_save(self) -> None:
        """Validate the controls and return a tag filter to the application."""
        field_set = self.query_one("#filter-field", RadioSet)
        pressed = field_set.pressed_button
        field = (
            TagFilterField.DETAILS
            if pressed is not None and pressed.id == "filter-details"
            else TagFilterField.MERCHANT
        )
        match_selector = "#details-match" if field is TagFilterField.DETAILS else "#merchant-match"
        match = self.query_one(match_selector, Input).value
        raw_tags = self.query_one("#filter-tags", Input).value

        try:
            tag_filter = TagFilter(field=field, match=match, tags=tuple(raw_tags.split(",")))
        except TagFilterError as error:
            self.query_one("#filter-error", Static).update(str(error))
            return
        self.dismiss(tag_filter)

    def action_cancel(self) -> None:
        """Close the dialog without creating a filter."""
        self.dismiss(None)


class DollarbyApp(App[None]):
    """Browse and, eventually, categorise transactions in one statement."""

    TITLE = "Dollarby"
    CSS = """
    Screen { layout: vertical; }

    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }

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

    TransactionTable {
        height: 1fr;
        border-top: solid $accent;
    }

    .status-bar { height: 1; }

    .status-summary, .status-total {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    .status-summary { width: 1fr; }

    .status-total {
        width: auto;
        content-align: right middle;
    }

    #tag-browser { height: 1fr; }

    #tag-list {
        width: 28;
        border-right: solid $accent;
    }

    #tag-list > ListItem { padding: 0 1; }

    #tag-results { width: 1fr; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("1", "show_statements", "Statements", priority=True),
        Binding("2", "show_tags", "Tags", priority=True),
        Binding("a", "add_tag_filter", "Add tag filter"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
    ]

    def __init__(self, statement: Statement) -> None:
        """Create the transaction browser for one statement."""
        super().__init__()
        self.statement = statement
        self.sub_title = statement.path.name
        self._tables_ready = False

    @override
    def compose(self) -> ComposeResult:
        """Compose the initial transaction-browser screen."""
        yield Header()
        with TabbedContent(initial="statements", id="views"):
            with TabPane("1 Statements", id="statements"):
                with Horizontal(id="toolbar"):
                    yield Label("Show", id="view-label")
                    yield Select[TransactionView](
                        VIEW_OPTIONS,
                        value=TransactionView.ALL,
                        allow_blank=False,
                        compact=True,
                        id="transaction-view",
                    )
                yield TransactionTable(id="transactions", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="status-bar"):
                    yield Static(id="summary", classes="status-summary")
                    yield Static(id="total", classes="status-total")
            with TabPane("2 Tags", id="tags"), Horizontal(id="tag-browser"):
                yield TagList(self.statement.tags, widget_id="tag-list")
                with Vertical(id="tag-results"):
                    yield TransactionTable(
                        id="tag-transactions",
                        cursor_type="row",
                        zebra_stripes=True,
                    )
                    with Horizontal(classes="status-bar"):
                        yield Static(id="tag-summary", classes="status-summary")
                        yield Static(id="tag-total", classes="status-total")
        yield Footer()

    def on_mount(self) -> None:
        """Set up and populate the transaction table."""
        statement_table = self.query_one("#transactions", TransactionTable)
        tag_table = self.query_one("#tag-transactions", TransactionTable)
        statement_table.add_columns(*TRANSACTION_COLUMNS)
        tag_table.add_columns(*TRANSACTION_COLUMNS)
        self._tables_ready = True
        self._show_transactions(TransactionView.ALL)
        self._show_tag_transactions(self.query_one(TagList).active_tag)
        statement_table.focus()

    @on(Select.Changed, "#transaction-view")
    def change_transaction_view(self, event: Select.Changed) -> None:
        """Replace the rows when the selected categorisation view changes."""
        if isinstance(event.value, TransactionView):
            self._show_transactions(event.value)

    @on(ListView.Highlighted, "#tag-list")
    def change_tag(self, event: ListView.Highlighted) -> None:
        """Show transactions carrying the highlighted tag."""
        if self._tables_ready:
            tag_list = cast("TagList", event.list_view)
            self._show_tag_transactions(tag_list.active_tag)

    @on(TabbedContent.TabActivated, "#views")
    def focus_active_view(self, event: TabbedContent.TabActivated) -> None:
        """Move focus into the active tab's primary list."""
        if not self._tables_ready:
            return
        if event.pane.id == "tags":
            self.query_one("#tag-list", TagList).focus()
        else:
            self.query_one("#transactions", TransactionTable).focus()

    def action_show_statements(self) -> None:
        """Activate the Statements tab."""
        self.query_one("#views", TabbedContent).active = "statements"

    def action_show_tags(self) -> None:
        """Activate the Tags tab."""
        self.query_one("#views", TabbedContent).active = "tags"

    def action_add_tag_filter(self) -> None:
        """Open a tag-filter dialog pre-filled from the active transaction table."""
        merchant, details = self._selected_transaction_text()
        self.push_screen(
            AddTagFilterDialog(merchant=merchant, details=details),
            self._apply_tag_filter,
        )

    async def _apply_tag_filter(self, tag_filter: TagFilter | None) -> None:
        """Apply a saved filter and refresh both transaction views."""
        if tag_filter is None:
            return

        match_count = self.statement.apply_tag_filter(tag_filter)
        selected_view = self.query_one("#transaction-view", Select).value
        view = selected_view if isinstance(selected_view, TransactionView) else TransactionView.ALL
        self._show_transactions(view)

        tag_list = self.query_one("#tag-list", TagList)
        self._tables_ready = False
        await tag_list.replace_tags(self.statement.tags, active_tag=tag_filter.tags[0])
        self._tables_ready = True
        self._show_tag_transactions(tag_list.active_tag)

        if self.query_one("#views", TabbedContent).active == "tags":
            tag_list.focus()
        self.notify(f"Applied {', '.join(tag_filter.tags)} to {match_count:,} transaction(s)")

    def _selected_transaction_text(self) -> tuple[str, str]:
        """Return merchant and details from the active view's selected transaction."""
        tab = self.query_one("#views", TabbedContent).active
        selector = "#tag-transactions" if tab == "tags" else "#transactions"
        table = self.query_one(selector, TransactionTable)
        if not table.row_count or table.cursor_row >= table.row_count:
            return "", ""

        row = table.get_row_at(table.cursor_row)
        return str(row[3]), str(row[4])

    def _show_transactions(self, view: TransactionView) -> None:
        """Populate the table with transactions from one view."""
        table = self.query_one("#transactions", TransactionTable)
        selected = self.statement.select(view)
        self._populate_transactions(table, selected)

        summary = self.query_one("#summary", Static)
        summary.update(
            f"{len(selected):,} shown · "
            f"{self.statement.unprocessed_count:,} unprocessed · "
            f"{self.statement.processed_count:,} processed · "
            f"{len(self.statement.transactions):,} total",
        )
        self._show_total("#total", selected)

    def _show_tag_transactions(self, tag: str | None) -> None:
        """Populate the tag browser for one highlighted tag."""
        table = self.query_one("#tag-transactions", TransactionTable)
        selected = (
            self.statement.transactions.iloc[0:0] if tag is None else self.statement.select_tag(tag)
        )
        self._populate_transactions(table, selected)

        summary = self.query_one("#tag-summary", Static)
        if tag is None:
            summary.update("No tags in this statement")
        else:
            summary.update(f"{len(selected):,} shown · {tag}")
        self._show_total("#tag-total", selected)

    def _show_total(self, selector: str, transactions: pd.DataFrame) -> None:
        """Show the total amount for the transactions visible in one view."""
        total = float(cast("int | float", transactions["amount"].sum()))
        self.query_one(selector, Static).update(f"Total: ${total:,.2f}")

    def _populate_transactions(
        self,
        table: TransactionTable,
        transactions: pd.DataFrame,
    ) -> None:
        """Render canonical transactions into one transaction table."""
        table.clear()
        for transaction in transactions.itertuples(index=False):
            # pandas-stubs exposes each named tuple value as a broad union; the
            # statement loader establishes these concrete canonical dtypes.
            amount = float(cast("int | float", transaction.amount))
            date = cast("datetime", transaction.date)
            tags = sorted(cast("frozenset[str]", transaction.tags))
            table.add_row(
                _status(processed=bool(tags)),
                date.strftime("%Y-%m-%d"),
                _amount(amount),
                str(transaction.merchant_name),
                str(transaction.transaction_details),
                str(transaction.transaction_type),
                ", ".join(tags),
                key=str(cast("int", transaction.source_row)),
            )


def run_tui(statement: Statement) -> None:
    """Run Dollarby's full-screen transaction browser."""
    DollarbyApp(statement).run()


def _status(*, processed: bool) -> Text:
    """Render whether a transaction has at least one tag."""
    if processed:
        return Text("✓", style="green")
    return Text("!", style="yellow")


def _amount(amount: float) -> Text:
    """Render an amount with sign-aware colour."""
    style = "green" if amount >= 0 else "red"
    return Text(f"${amount:,.2f}", style=style, justify="right")
