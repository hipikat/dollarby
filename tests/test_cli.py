"""Tests for Dollarby's Click boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from dollarby import cli as cli_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from dollarby.data import Statement
    from dollarby.processor import ProcessorDocument


def test_open_dispatches_to_the_tui(
    statement_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate and load a statement before launching Textual."""
    opened: list[tuple[Statement, ProcessorDocument]] = []

    def capture_tui(statement: Statement, document: ProcessorDocument) -> None:
        opened.append((statement, document))

    monkeypatch.setattr(cli_module, "run_tui", capture_tui)

    result = CliRunner().invoke(cli_module.cli, ["open", str(statement_path)])

    assert result.exit_code == 0, result.output
    assert len(opened) == 1
    assert opened[0][0].path == statement_path
    assert opened[0][1].path == cli_module.DEFAULT_PROCESSOR_PATH
