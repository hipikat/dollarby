"""Tests for Dollarby's Textual transaction browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from textual.containers import Vertical
from textual.widgets import Input, RadioButton, Select, Static, TabbedContent

from dollarby.data import Statement, TransactionView
from dollarby.tui import AddTagDialog, DollarbyApp, TagList, TransactionTable

if TYPE_CHECKING:
    from dollarby.processor import ProcessorDocument

pytestmark = pytest.mark.asyncio


async def test_transaction_view_selector_filters_rows(
    partly_processed_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Default to all transactions and switch between processing states."""
    app = DollarbyApp(partly_processed_statement, processor_document)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)
        selector = app.query_one("#transaction-view", Select)
        summary = app.query_one("#summary", Static)
        total = app.query_one("#total", Static)

        assert selector.value is TransactionView.ALL
        assert table.row_count == len(partly_processed_statement.transactions)
        assert summary.region.x < total.region.x
        assert str(total.content) == "Total: $-3.00"

        selector.value = TransactionView.UNPROCESSED
        await pilot.pause()
        assert table.row_count == 1
        assert str(total.content) == "Total: $-2.00"

        selector.value = TransactionView.PROCESSED
        await pilot.pause()
        assert table.row_count == 1
        assert str(total.content) == "Total: $-1.00"


async def test_processed_row_displays_its_processor_tags(
    partly_processed_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Show processor-derived tags alongside a transaction in the default view."""
    app = DollarbyApp(partly_processed_statement, processor_document)

    async with app.run_test():
        table = app.query_one("#transactions", TransactionTable)

        row = table.get_row_at(0)
        assert row[6] == "food, restaurant"


async def test_number_keys_select_application_tabs(
    statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Select the Statements and Tags tabs by their displayed number."""
    app = DollarbyApp(statement, processor_document)

    async with app.run_test() as pilot:
        tabs = app.query_one("#views", TabbedContent)

        assert tabs.active == "statements"

        await pilot.press("2")
        assert tabs.active == "tags"
        assert app.focused is app.query_one("#tag-list", TagList)
        assert str(app.query_one("#tag-total", Static).content) == "Total: $0.00"

        await pilot.press("1")
        assert tabs.active == "statements"
        assert app.focused is app.query_one("#transactions", TransactionTable)


async def test_tag_list_filters_transactions(
    multi_tagged_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """List tags alphabetically and update the transaction list from its highlight."""
    app = DollarbyApp(multi_tagged_statement, processor_document)

    async with app.run_test() as pilot:
        await pilot.press("2")
        tag_list = app.query_one("#tag-list", TagList)
        table = app.query_one("#tag-transactions", TransactionTable)
        total = app.query_one("#tag-total", Static)

        assert tag_list.tags == ("food", "phone & internet", "restaurant")
        assert tag_list.active_tag == "food"
        assert tag_list.region.x < table.region.x
        assert table.row_count == 1
        assert table.get_row_at(0)[3] == "Grill'd"
        assert str(total.content) == "Total: $-1.00"

        await pilot.press("j")
        assert tag_list.active_tag == "phone & internet"
        assert table.row_count == 1
        assert table.get_row_at(0)[3] == "Vodafone"
        assert str(total.content) == "Total: $-2.00"


async def test_h_toggles_ignored_transactions_globally(
    hidden_tagged_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Share hidden-tag visibility between Statements, Tags, and future app views."""
    app = DollarbyApp(hidden_tagged_statement, processor_document)
    binding = next(binding for binding in DollarbyApp.BINDINGS if binding.key == "h")

    async with app.run_test() as pilot:
        statement_table = app.query_one("#transactions", TransactionTable)
        statement_total = app.query_one("#total", Static)
        tag_list = app.query_one("#tag-list", TagList)

        assert binding.description == "Toggle ignored"
        assert statement_table.row_count == 1
        assert str(statement_total.content) == "Total: $-2.00"
        assert tag_list.tags == ()

        await pilot.press("h", "2")

        tag_table = app.query_one("#tag-transactions", TransactionTable)
        assert statement_table.row_count == len(hidden_tagged_statement.transactions)
        assert str(statement_total.content) == "Total: $-3.00"
        assert tag_list.tags == ("Alcohol",)
        assert tag_table.row_count == 1

        await pilot.press("h", "1")

        assert tag_list.tags == ()
        assert tag_table.row_count == 0
        assert statement_table.row_count == 1


async def test_add_tag_dialog_is_prefilled_from_selected_transaction(
    statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Open the modal with editable merchant and details text from the selected row."""
    app = DollarbyApp(statement, processor_document)
    source = processor_document.path.read_text(encoding="utf-8")

    async with app.run_test() as pilot:
        await pilot.press("j", "a")

        dialog = app.screen
        assert isinstance(dialog, AddTagDialog)
        panel = dialog.query_one("#tag-filter-dialog", Vertical)
        merchant_radio = dialog.query_one("#filter-merchant", RadioButton)
        details_radio = dialog.query_one("#filter-details", RadioButton)
        merchant_input = dialog.query_one("#merchant-match", Input)
        details_input = dialog.query_one("#details-match", Input)

        assert panel.region.width >= app.size.width * 4 // 5
        assert panel.region.x == (app.size.width - panel.region.width) // 2
        assert merchant_radio.region.y == merchant_input.region.y
        assert details_radio.region.y == details_input.region.y
        assert merchant_input.value == "Example Merchant 2"
        assert details_input.value == "Example purchase 2"
        assert merchant_input.has_focus

        merchant_input.value = "Edited Merchant"
        await pilot.press("escape")

        assert not isinstance(app.screen, AddTagDialog)
        assert processor_document.path.read_text(encoding="utf-8") == source


async def test_add_tag_rejects_processed_transaction_in_tags_view(
    multi_tagged_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Avoid appending an unreachable final rule for an already processed row."""
    app = DollarbyApp(multi_tagged_statement, processor_document)

    async with app.run_test() as pilot:
        await pilot.press("2", "a")

        dialog = app.screen
        assert not isinstance(dialog, AddTagDialog)


async def test_add_tag_dialog_saves_merchant_rule_and_refreshes_views(
    statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Apply comma-separated tags to all matching merchants and expose the new tags."""
    app = DollarbyApp(statement, processor_document)

    async with app.run_test() as pilot:
        await pilot.press("a")
        dialog = app.screen
        assert isinstance(dialog, AddTagDialog)
        dialog.query_one("#merchant-match", Input).value = "example merchant"
        dialog.query_one("#filter-tags", Input).value = "Work, recurring, work"

        await pilot.click("#save-filter")
        await pilot.pause()

        assert not isinstance(app.screen, AddTagDialog)
        written_rule = processor_document.processor.tagging.rules[0].matches[-1]
        assert written_rule.contains == "example merchant"
        assert written_rule.tags == ("Work", "recurring")
        assert statement.tags == ("recurring", "Work")
        assert all(
            tags == frozenset({"Work", "recurring"}) for tags in statement.transactions["tags"]
        )
        assert app.query_one("#tag-list", TagList).active_tag == "Work"
        statement_row = app.query_one("#transactions", TransactionTable).get_row_at(0)
        assert statement_row[6] == "recurring, Work"


async def test_add_tag_dialog_applies_selected_details_field(
    statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Use the selected radio field and show validation errors without closing the modal."""
    app = DollarbyApp(statement, processor_document)

    async with app.run_test() as pilot:
        await pilot.press("a")
        dialog = app.screen
        assert isinstance(dialog, AddTagDialog)
        dialog.query_one("#filter-details", RadioButton).value = True
        dialog.query_one("#details-match", Input).value = "PURCHASE 2"

        await pilot.click("#save-filter")
        assert isinstance(app.screen, AddTagDialog)
        assert str(dialog.query_one("#filter-error", Static).content) == "Enter at least one tag"

        dialog.query_one("#filter-tags", Input).value = "Personal"
        dialog.action_save()
        await pilot.pause()

        written_rule = processor_document.processor.tagging.rules[1].matches[-1]
        assert written_rule.contains == "PURCHASE 2"
        assert written_rule.tags == ("Personal",)
        assert list(statement.transactions["tags"]) == [
            frozenset(),
            frozenset({"Personal"}),
        ]


async def test_processor_write_failure_keeps_add_tag_open(
    statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Show write errors without closing the modal or changing dataframe tags."""
    app = DollarbyApp(statement, processor_document)
    source = processor_document.path.read_text(encoding="utf-8")

    async with app.run_test() as pilot:
        await pilot.press("a")
        dialog = app.screen
        assert isinstance(dialog, AddTagDialog)
        dialog.query_one("#filter-tags", Input).value = "Work"
        processor_document.path.write_text(f"{source}\n", encoding="utf-8")

        await pilot.click("#save-filter")

        assert isinstance(app.screen, AddTagDialog)
        error = str(dialog.query_one("#filter-error", Static).content)
        assert "changed after Dollarby loaded" in error
        assert all(not tags for tags in statement.transactions["tags"])


async def test_j_and_k_move_the_transaction_cursor(
    large_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Move down with j and back up with k while the table has focus."""
    app = DollarbyApp(large_statement, processor_document)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)

        await pilot.press("j", "j", "k")

        assert table.cursor_row == 1


async def test_ctrl_keys_move_by_full_and_half_pages(
    large_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Support Vim's full-page and half-page vertical movements."""
    app = DollarbyApp(large_statement, processor_document)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)

        await pilot.press("ctrl+f")
        full_page_row = table.cursor_row
        assert full_page_row > 1

        await pilot.press("g", "ctrl+d")
        half_page_row = table.cursor_row
        assert 0 < half_page_row < full_page_row

        await pilot.press("ctrl+u")
        assert table.cursor_row == 0

        await pilot.press("ctrl+f", "ctrl+b")
        assert table.cursor_row == 0


async def test_g_and_uppercase_g_move_to_extremes(
    large_statement: Statement,
    processor_document: ProcessorDocument,
) -> None:
    """Use g and G for the first and last transaction."""
    app = DollarbyApp(large_statement, processor_document)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)

        await pilot.press("G")
        assert table.cursor_row == len(large_statement.transactions) - 1

        await pilot.press("g")
        assert table.cursor_row == 0
