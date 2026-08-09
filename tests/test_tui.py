"""Tests for Dollarby's Textual transaction browser."""

from __future__ import annotations

import pytest
from textual.widgets import Select, Static, TabbedContent

from dollarby.data import Statement, TransactionView
from dollarby.tui import DollarbyApp, TagList, TransactionTable

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
