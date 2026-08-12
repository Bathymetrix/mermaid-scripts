# mermaid-scripts

Miscellaneous maintenance, migration, reconciliation, audit, and operational
scripts for the MERMAID ecosystem.

These scripts are generally one-off or repository-level utilities that do not
belong in a dedicated package such as `mermaid-records`,
`mermaid-timelines`, `mermaid-buffer`, or `mermaid-catalogs`.

## Requirements

- Zsh
- Python 3.9+

All scripts are intended to be run from the command line on macOS/Linux.

## Included Scripts

### reconcile_server.py

Conservatively reconcile multiple MERMAID server trees into a single flat
processing archive.

Features:

- Groups files by basename across multiple source trees
- Copies byte-identical binary files
- Merges compatible text records
- Detects conflicting records requiring manual review
- Generates reconciliation, review, and source-status reports
- Never silently overwrites conflicting content

Example:

```bash
scripts/reconcile_server.py --dry-run

scripts/reconcile_server.py \
    --src "$MERMAID/server" \
    --src "$MERMAID/server_jamstec" \
    --dest "$MERMAID/server_everyone"
```

### render_record_views.py

Build disposable, grep-friendly, chronologically sorted text views from the
canonical `mermaid-records` JSONL corpus. The destination is always explicit;
the script never modifies `$MERMAID/records`.

```bash
scripts/render_record_views.py
```

The script defaults to `$MERMAID/records` and `$MERMAID/record-views`; use
`--input-dir` / `-i` and `--output-dir` / `-o` to override either location. It
fully rebuilds each discovered family file atomically. Ordinary LOG and
Iridium event rows render their upstream parsed `message`; parameter, CTD, and
testmode episodes retain their preserved source lines. Lines without an
individual normalized time render as `UNTIMED` rather than being assigned an
invented timestamp.

## Philosophy

These scripts prioritize:

- Conservative data handling
- Explicit review of conflicts
- Reproducibility
- Minimal dependencies
- Preservation of original source data
