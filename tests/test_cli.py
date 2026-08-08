"""Tests for Dollarby's Click boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from dollarby import cli as cli_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from dollarby.data import Statement


def test_open_dispatches_to_the_tui(
    statement_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate and load a statement before launching Textual."""
    opened_statements: list[Statement] = []
    monkeypatch.setattr(cli_module, "run_tui", opened_statements.append)

    result = CliRunner().invoke(cli_module.cli, ["open", str(statement_path)])

    assert result.exit_code == 0, result.output
    assert len(opened_statements) == 1
    assert opened_statements[0].path == statement_path
