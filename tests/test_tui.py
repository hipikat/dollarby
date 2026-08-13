"""Tests for Dollarby's Textual transaction browser."""

from __future__ import annotations

import pytest
from textual.containers import Vertical
from textual.widgets import Input, RadioButton, Select, Static, TabbedContent

from dollarby.data import Statement, TagFilterField, TransactionView
from dollarby.tui import AddTagFilterDialog, DollarbyApp, TagList, TransactionTable

pytestmark = pytest.mark.asyncio


async def test_transaction_view_selector_filters_rows(
    partly_processed_statement: Statement,
) -> None:
    """Default to all transactions and switch between processing states."""
    app = DollarbyApp(partly_processed_statement)

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
) -> None:
    """Show processor-derived tags alongside a transaction in the default view."""
    app = DollarbyApp(partly_processed_statement)

    async with app.run_test():
        table = app.query_one("#transactions", TransactionTable)

        row = table.get_row_at(0)
        assert row[6] == "food, restaurant"


async def test_number_keys_select_application_tabs(statement: Statement) -> None:
    """Select the Statements and Tags tabs by their displayed number."""
    app = DollarbyApp(statement)

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
) -> None:
    """List tags alphabetically and update the transaction list from its highlight."""
    app = DollarbyApp(multi_tagged_statement)

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


async def test_add_filter_dialog_is_prefilled_from_selected_transaction(
    statement: Statement,
) -> None:
    """Open the modal with editable merchant and details text from the selected row."""
    app = DollarbyApp(statement)

    async with app.run_test() as pilot:
        await pilot.press("j", "a")

        dialog = app.screen
        assert isinstance(dialog, AddTagFilterDialog)
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

        assert not isinstance(app.screen, AddTagFilterDialog)
        assert statement.tag_filters == []


async def test_add_filter_dialog_is_prefilled_from_tags_view(
    multi_tagged_statement: Statement,
) -> None:
    """Use the selected transaction from the active Tags tab when opening the modal."""
    app = DollarbyApp(multi_tagged_statement)

    async with app.run_test() as pilot:
        await pilot.press("2", "a")

        dialog = app.screen
        assert isinstance(dialog, AddTagFilterDialog)
        assert dialog.query_one("#merchant-match", Input).value == "Grill'd"

        await pilot.press("escape")


async def test_filter_dialog_saves_merchant_filter_and_refreshes_views(
    statement: Statement,
) -> None:
    """Apply comma-separated tags to all matching merchants and expose the new tags."""
    app = DollarbyApp(statement)

    async with app.run_test() as pilot:
        await pilot.press("a")
        dialog = app.screen
        assert isinstance(dialog, AddTagFilterDialog)
        dialog.query_one("#merchant-match", Input).value = "example merchant"
        dialog.query_one("#filter-tags", Input).value = "Work, recurring, work"

        await pilot.click("#save-filter")
        await pilot.pause()

        assert not isinstance(app.screen, AddTagFilterDialog)
        assert statement.tag_filters[0].field is TagFilterField.MERCHANT
        assert statement.tags == ("recurring", "Work")
        assert all(
            tags == frozenset({"Work", "recurring"}) for tags in statement.transactions["tags"]
        )
        assert app.query_one("#tag-list", TagList).active_tag == "Work"
        statement_row = app.query_one("#transactions", TransactionTable).get_row_at(0)
        assert statement_row[6] == "Work, recurring"


async def test_filter_dialog_applies_selected_details_field(statement: Statement) -> None:
    """Use the selected radio field and show validation errors without closing the modal."""
    app = DollarbyApp(statement)

    async with app.run_test() as pilot:
        await pilot.press("a")
        dialog = app.screen
        assert isinstance(dialog, AddTagFilterDialog)
        dialog.query_one("#filter-details", RadioButton).value = True
        dialog.query_one("#details-match", Input).value = "PURCHASE 2"

        await pilot.click("#save-filter")
        assert isinstance(app.screen, AddTagFilterDialog)
        assert str(dialog.query_one("#filter-error", Static).content) == "Enter at least one tag"

        dialog.query_one("#filter-tags", Input).value = "Personal"
        dialog.action_save()
        await pilot.pause()

        assert statement.tag_filters[0].field is TagFilterField.DETAILS
        assert list(statement.transactions["tags"]) == [
            frozenset(),
            frozenset({"Personal"}),
        ]


async def test_j_and_k_move_the_transaction_cursor(large_statement: Statement) -> None:
    """Move down with j and back up with k while the table has focus."""
    app = DollarbyApp(large_statement)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)

        await pilot.press("j", "j", "k")

        assert table.cursor_row == 1


async def test_ctrl_keys_move_by_full_and_half_pages(large_statement: Statement) -> None:
    """Support Vim's full-page and half-page vertical movements."""
    app = DollarbyApp(large_statement)

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


async def test_g_and_uppercase_g_move_to_extremes(large_statement: Statement) -> None:
    """Use g and G for the first and last transaction."""
    app = DollarbyApp(large_statement)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)

        await pilot.press("G")
        assert table.cursor_row == len(large_statement.transactions) - 1

        await pilot.press("g")
        assert table.cursor_row == 0
