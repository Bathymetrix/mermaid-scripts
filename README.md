# mermaid-scripts

Miscellaneous maintenance, migration, reconciliation, audit, and operational
scripts for the MERMAID ecosystem.

These scripts are generally one-off or repository-level utilities that do not
belong in a dedicated package such as `mermaid-records`,
`mermaid-timelines`, `mermaid-buffer`, or `mermaid-catalogs`.

## Requirements

- Zsh
- Python 3

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
./reconcile_server.py --dry-run

./reconcile_server.py \
    --src ~/mermaid/server \
    --src ~/mermaid/server_jamstec \
    --dest ~/mermaid/server_everyone
```

## Philosophy

These scripts prioritize:

- Conservative data handling
- Explicit review of conflicts
- Reproducibility
- Minimal dependencies
- Preservation of original source data
