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

Press `a` from either tab to open the Add Tag Filter dialog for the selected
transaction. Filters match editable Merchant or Details text case-insensitively
and apply comma-separated tags for the current session.
