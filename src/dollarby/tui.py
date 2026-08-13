"""Dollarby's interactive Textual application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast, override

from pydantic import ValidationError
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

from dollarby.data import Statement, TransactionView
from dollarby.processor import (
    NewTagRule,
    ProcessorDocument,
    ProcessorError,
    TagRuleField,
)

if TYPE_CHECKING:
    from collections.abc import Callable
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


@dataclass(frozen=True, slots=True)
class SelectedTransaction:
    """Retain the values needed by actions targeting a displayed transaction."""

    merchant: str
    details: str
    processed: bool


@dataclass(frozen=True, slots=True)
class SavedTagRule:
    """Report a successfully persisted rule and its dataframe effect."""

    rule: NewTagRule
    changed_transactions: int


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

    def __init__(self, *, widget_id: str) -> None:
        """Create a consistently configured transaction table."""
        super().__init__(id=widget_id, cursor_type="row", zebra_stripes=True)
        self._transactions: list[SelectedTransaction] = []

    @override
    def on_mount(self) -> None:
        """Install the canonical display columns."""
        self.add_columns(*TRANSACTION_COLUMNS)

    @property
    def selected_transaction(self) -> SelectedTransaction | None:
        """Return action-relevant values from the selected transaction."""
        if not self.row_count or self.cursor_row >= len(self._transactions):
            return None
        return self._transactions[self.cursor_row]

    def replace_transactions(self, transactions: pd.DataFrame) -> None:
        """Replace the rendered rows and their action metadata."""
        self.clear()
        self._transactions = []
        for transaction in transactions.itertuples(index=False):
            # pandas-stubs exposes each named tuple value as a broad union; the
            # statement loader establishes these concrete canonical dtypes.
            amount = float(cast("int | float", transaction.amount))
            date = cast("datetime", transaction.date)
            tags = sorted(
                cast("frozenset[str]", transaction.tags),
                key=lambda tag: (tag.casefold(), tag),
            )
            selected = SelectedTransaction(
                merchant=str(transaction.merchant_name),
                details=str(transaction.transaction_details),
                processed=bool(tags),
            )
            self._transactions.append(selected)
            self.add_row(
                _status(processed=selected.processed),
                date.strftime("%Y-%m-%d"),
                _amount(amount),
                selected.merchant,
                selected.details,
                str(transaction.transaction_type),
                ", ".join(tags),
                key=str(cast("int", transaction.source_row)),
            )

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


class TransactionResults(Vertical):
    """Compose and update a transaction table with its shared status bar."""

    def __init__(
        self,
        *,
        table_id: str,
        summary_id: str,
        total_id: str,
        widget_id: str | None = None,
    ) -> None:
        """Retain child identifiers used by existing application selectors."""
        super().__init__(id=widget_id)
        self._table_id = table_id
        self._summary_id = summary_id
        self._total_id = total_id

    @override
    def compose(self) -> ComposeResult:
        """Compose the table and its summary and total fields."""
        yield TransactionTable(widget_id=self._table_id)
        with Horizontal(classes="status-bar"):
            yield Static(id=self._summary_id, classes="status-summary")
            yield Static(id=self._total_id, classes="status-total")

    @property
    def table(self) -> TransactionTable:
        """Return this result set's transaction table."""
        return self.query_one(TransactionTable)

    def show(self, transactions: pd.DataFrame, *, summary: str) -> None:
        """Replace all visible transaction results and status text."""
        self.table.replace_transactions(transactions)
        self.query_one(f"#{self._summary_id}", Static).update(summary)
        total = float(cast("int | float", transactions["amount"].sum()))
        self.query_one(f"#{self._total_id}", Static).update(f"Total: {_money(total)}")


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

    async def replace_tags(self, tags: tuple[str, ...], *, active_tag: str | None) -> None:
        """Replace the available tags and highlight one requested tag."""
        self.index = None
        await self.clear()
        self.tags = tags
        await self.extend(ListItem(Label(tag)) for tag in tags)
        self.index = tags.index(active_tag) if active_tag in tags else 0 if tags else None


class AddTagDialog(ModalScreen[SavedTagRule | None]):
    """Collect and persist one field-specific tag rule."""

    CSS = """
    AddTagDialog {
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

    def __init__(
        self,
        *,
        merchant: str,
        details: str,
        save_rule: Callable[[NewTagRule], int],
    ) -> None:
        """Create a dialog pre-filled from an optional selected transaction."""
        super().__init__()
        self.merchant = merchant
        self.details = details
        self._save_rule = save_rule

    @override
    def compose(self) -> ComposeResult:
        """Compose the field, match-text, tag, and action controls."""
        with Vertical(id="tag-filter-dialog"):
            yield Label("Add Tag", id="filter-title")
            yield Static(
                "Whole-literal matching is case-insensitive and saved to this processor.",
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
            TagRuleField.DETAILS
            if pressed is not None and pressed.id == "filter-details"
            else TagRuleField.MERCHANT
        )
        match_selector = "#details-match" if field is TagRuleField.DETAILS else "#merchant-match"
        match = self.query_one(match_selector, Input).value
        raw_tags = self.query_one("#filter-tags", Input).value

        try:
            rule = NewTagRule(field=field, contains=match, tags=tuple(raw_tags.split(",")))
        except ValidationError as error:
            self.query_one("#filter-error", Static).update(_validation_message(error))
            return

        try:
            changed_transactions = self._save_rule(rule)
        except ProcessorError as error:
            self.query_one("#filter-error", Static).update(str(error))
            return
        self.dismiss(SavedTagRule(rule=rule, changed_transactions=changed_transactions))

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

    TransactionResults { height: 1fr; }

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
        Binding("1", "show_tab('statements')", "Statements", priority=True),
        Binding("2", "show_tab('tags')", "Tags", priority=True),
        Binding("a", "add_tag", "Add tag"),
        Binding("h", "toggle_ignored", "Toggle ignored"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
    ]

    def __init__(self, statement: Statement, processor_document: ProcessorDocument) -> None:
        """Create the transaction browser for one statement."""
        super().__init__()
        self.statement = statement
        self.processor_document = processor_document
        self.sub_title = statement.path.name
        self._tables_ready = False
        self._show_hidden_tags = False

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
                yield TransactionResults(
                    table_id="transactions",
                    summary_id="summary",
                    total_id="total",
                )
            with TabPane("2 Tags", id="tags"), Horizontal(id="tag-browser"):
                yield TagList(self._visible_tags(), widget_id="tag-list")
                yield TransactionResults(
                    table_id="tag-transactions",
                    summary_id="tag-summary",
                    total_id="tag-total",
                    widget_id="tag-results",
                )
        yield Footer()

    def on_mount(self) -> None:
        """Set up and populate the transaction table."""
        statement_table = self.query_one("#transactions", TransactionTable)
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
    def focus_active_view(self, _event: TabbedContent.TabActivated) -> None:
        """Move focus into the active tab's primary list."""
        if not self._tables_ready:
            return
        self._focus_active_view()

    def action_show_tab(self, tab_id: str) -> None:
        """Activate one application tab by identifier."""
        self.query_one("#views", TabbedContent).active = tab_id

    async def action_toggle_ignored(self) -> None:
        """Toggle application-wide visibility of hidden-tagged transactions."""
        tag_list = self.query_one("#tag-list", TagList)
        active_tag = tag_list.active_tag
        self._show_hidden_tags = not self._show_hidden_tags
        await self._refresh_views(active_tag=active_tag)
        self._focus_active_view()
        state = "Showing" if self._show_hidden_tags else "Hiding"
        self.notify(f"{state} ignored transactions")

    def action_add_tag(self) -> None:
        """Open Add Tag for the active unprocessed transaction."""
        transaction = self._active_transaction_table().selected_transaction
        if transaction is None:
            self.notify("Select an unprocessed transaction first", severity="warning")
            return
        if transaction.processed:
            self.notify(
                "Add Tag is currently limited to unprocessed transactions",
                severity="warning",
            )
            return

        self.push_screen(
            AddTagDialog(
                merchant=transaction.merchant,
                details=transaction.details,
                save_rule=self._persist_tag_rule,
            ),
            self._tag_rule_saved,
        )

    def _persist_tag_rule(self, rule: NewTagRule) -> int:
        """Save one rule before deterministically reprocessing the statement."""
        processor = self.processor_document.add_tag_rule(rule)
        return self.statement.reprocess(processor)

    async def _tag_rule_saved(self, result: SavedTagRule | None) -> None:
        """Refresh both transaction views after a successful processor write."""
        if result is None:
            return

        await self._refresh_views(active_tag=result.rule.tags[0])
        self._focus_active_view()
        self.notify(
            f"Saved {', '.join(result.rule.tags)} for "
            f"{result.changed_transactions:,} transaction(s)",
        )

    def _active_transaction_table(self) -> TransactionTable:
        """Return the transaction table displayed in the active tab."""
        tab = self.query_one("#views", TabbedContent).active
        selector = "#tag-transactions" if tab == "tags" else "#transactions"
        return self.query_one(selector, TransactionTable)

    def _focus_active_view(self) -> None:
        """Focus the primary control in the currently active tab."""
        if self.query_one("#views", TabbedContent).active == "tags":
            self.query_one("#tag-list", TagList).focus()
        else:
            self.query_one("#transactions", TransactionTable).focus()

    async def _refresh_views(self, *, active_tag: str | None) -> None:
        """Refresh every view from the application-wide hidden-tag state."""
        selected_view = self.query_one("#transaction-view", Select).value
        view = selected_view if isinstance(selected_view, TransactionView) else TransactionView.ALL
        self._show_transactions(view)

        tag_list = self.query_one("#tag-list", TagList)
        self._tables_ready = False
        await tag_list.replace_tags(self._visible_tags(), active_tag=active_tag)
        self._tables_ready = True
        self._show_tag_transactions(tag_list.active_tag)

    @property
    def _hidden_tags(self) -> tuple[str, ...]:
        """Return the active processor's globally hidden tags."""
        return self.processor_document.processor.tagging.hidden_tags

    def _select_transactions(self, view: TransactionView) -> pd.DataFrame:
        """Select rows using the global hidden-tag visibility state."""
        return self.statement.select(
            view,
            hidden_tags=self._hidden_tags,
            include_hidden=self._show_hidden_tags,
        )

    def _visible_tags(self) -> tuple[str, ...]:
        """Return tags carried by transactions visible in every application view."""
        return self.statement.tags_for(self._select_transactions(TransactionView.ALL))

    def _show_transactions(self, view: TransactionView) -> None:
        """Populate the table with transactions from one view."""
        selected = self._select_transactions(view)
        unprocessed_count = len(self._select_transactions(TransactionView.UNPROCESSED))
        processed_count = len(self._select_transactions(TransactionView.PROCESSED))
        total_count = len(self._select_transactions(TransactionView.ALL))
        summary = (
            f"{len(selected):,} shown · {unprocessed_count:,} unprocessed · "
            f"{processed_count:,} processed · {total_count:,} total"
        )
        self.query_one("#statements TransactionResults", TransactionResults).show(
            selected,
            summary=summary,
        )

    def _show_tag_transactions(self, tag: str | None) -> None:
        """Populate the tag browser for one highlighted tag."""
        selected = (
            self.statement.transactions.iloc[0:0]
            if tag is None
            else self.statement.select_tag(
                tag,
                hidden_tags=self._hidden_tags,
                include_hidden=self._show_hidden_tags,
            )
        )
        summary = "No tags in this statement" if tag is None else f"{len(selected):,} shown · {tag}"
        self.query_one("#tag-results", TransactionResults).show(selected, summary=summary)


def run_tui(statement: Statement, processor_document: ProcessorDocument) -> None:
    """Run Dollarby's full-screen transaction browser."""
    DollarbyApp(statement, processor_document).run()


def _status(*, processed: bool) -> Text:
    """Render whether a transaction has at least one tag."""
    if processed:
        return Text("✓", style="green")
    return Text("!", style="yellow")


def _amount(amount: float) -> Text:
    """Render an amount with sign-aware colour."""
    style = "green" if amount >= 0 else "red"
    return Text(_money(amount), style=style, justify="right")


def _money(amount: float) -> str:
    """Format one monetary value consistently across tables and totals."""
    return f"${amount:,.2f}"


def _validation_message(error: ValidationError) -> str:
    """Extract the first actionable message from Pydantic validation output."""
    message = str(error.errors()[0]["msg"])
    return message.removeprefix("Value error, ")
