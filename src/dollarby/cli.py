"""Dollarby's Click command-line interface."""

from __future__ import annotations

from pathlib import Path

import click

from dollarby.data import StatementError, load_statement
from dollarby.processor import DEFAULT_PROCESSOR_PATH, ProcessorDocument, ProcessorError
from dollarby.tui import run_tui


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Personal tax and finance helpers."""


@cli.command("open")
@click.argument(
    "statement_file",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
def open_statement(statement_file: Path) -> None:
    """Open STATEMENT_FILE in Dollarby's interactive transaction browser."""
    try:
        processor_document = ProcessorDocument.load(DEFAULT_PROCESSOR_PATH)
        statement = load_statement(statement_file, processor_document.processor)
    except (ProcessorError, StatementError) as error:
        raise click.ClickException(str(error)) from error

    run_tui(statement, processor_document)
