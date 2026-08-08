"""Tests for Dollarby's Textual transaction browser."""

from __future__ import annotations

import pytest
from textual.widgets import Select

from dollarby.data import Statement, TransactionView
from dollarby.tui import DollarbyApp, TransactionTable

pytestmark = pytest.mark.asyncio


async def test_transaction_view_selector_filters_rows(
    categorised_statement: Statement,
) -> None:
    """Switch among uncategorised, categorised, and all transactions."""
    app = DollarbyApp(categorised_statement)

    async with app.run_test() as pilot:
        table = app.query_one("#transactions", TransactionTable)
        selector = app.query_one("#transaction-view", Select)

        assert table.row_count == 1

        selector.value = TransactionView.CATEGORISED
        await pilot.pause()
        assert table.row_count == 1

        selector.value = TransactionView.ALL
        await pilot.pause()
        assert table.row_count == len(categorised_statement.transactions)


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
