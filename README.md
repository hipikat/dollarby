# Dollarby

Personal tax and finance helpers.

## Open a statement

```console
uv run dollarby open statements/Transactions-2025-2026.csv
```

The Textual interface applies the configured processor and opens on a Statements
tab, which displays transaction tags and can filter to processed or unprocessed
rows. The Tags tab lists all tags and the transactions carrying the active tag.
Each view totals its currently visible transactions in the status bar.
Transactions carrying processor-defined hidden tags are omitted by default;
press `h` to show or hide ignored transactions across every view.

Press `a` on an unprocessed transaction to open the Add Tag dialog. It saves an
editable, case-insensitive Merchant or Details match and its comma-separated tags
to the active processor, then refreshes the statement from the persisted rules.
