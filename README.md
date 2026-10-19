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

### rebuild_processed_mirrors.py

Rebuild four flat symlink directories from the processed archive:

| Destination | Source files | Link names |
| --- | --- | --- |
| `waveforms/sac/` | `*.sac` | Original basename |
| `waveforms/mseed/` | `*.mseed` | Original basename |
| `metadata/geocsv/` | `geo_*.csv` | `<instrument>-<basename>` |
| `metadata/gps/` | `gps.txt`, `gps.csv` | `<instrument>-<basename>` |

```bash
scripts/rebuild_processed_mirrors.py
scripts/rebuild_processed_mirrors.py --processed-dir /path/to/processed --output-dir /path/to/mirrors
```

Defaults are `$MERMAID/processed` for the source and `$MERMAID` for the output
root, falling back to `~/mermaid/processed` and `~/mermaid` when `MERMAID` is
unset. Source traversal is recursive; the instrument prefix is the first
directory below the processed root. For example,
`processed/452.020-P-06/geo_DET_REQ.csv` becomes
`metadata/geocsv/452.020-P-06-geo_DET_REQ.csv`.

Each run replaces all symlinks in these four directories, including stale or
broken links, with absolute links to the source paths. Matching is case-sensitive,
and all cycles are included. Duplicate link names, a missing source directory,
or non-symlink contents in a mirror abort the run before existing links are
removed. Mirror directories themselves must not be symlinks. Other contents
of `waveforms/` and `metadata/`, including parent-level `.git/` directories,
are preserved. Source files are never copied or modified. This script runs
independently of `automaid`; it does not change its processing workflow.

### countsac.py

Report the total number of processed lower-case `.sac` files for each
instrument, split into detected (`.DET.`) and requested (`.REQ.`) waveforms.
The report includes the latest UTC start date from each class, read from the
SAC filename. By default it reads `$MERMAID/processed_everyone`.

```bash
scripts/countsac.py
scripts/countsac.py --sacdir "$MERMAID/processed_everyone"
scripts/countsac.py --sacdir "$MERMAID/processed_everyone" --exclude=OtherSubstring
```

SAC paths containing `IcCycle` are excluded by default. `--exclude` replaces
that exclusion substring; pass `--exclude=` to include all SAC paths.

### countevt.py

Report EVT coverage of the processed lower-case `.sac` archive for each
instrument. The SAC inventory is authoritative: the main table counts only
EVT files whose basenames correspond to a SAC file, split by reviewed
identified, reviewed unidentified, and unreviewed status, plus SAC files with
no EVT. DET and REQ subtotals use the SAC filename classification.

```bash
scripts/countevt.py
scripts/countevt.py \
    --sacdir "$MERMAID/processed_everyone" \
    --evtdir "$MERMAID/events_everyone" \
    --exclude=OtherSubstring
```

`--sacdir` and `--evtdir` default to `$MERMAID/processed_everyone` and
`$MERMAID/events_everyone`, respectively, when `MERMAID` is set. The event
archive must contain the relevant `reviewed/` and `unreviewed/` trees. The
report ends with an `EXCEPTIONS` section that lists prelim EVT files, EVT files
without a matching SAC, reviewed EVT files outside the identified/unidentified
directories, and duplicate EVT associations.

SAC paths containing `IcCycle` are excluded from the inventory by default.
`--exclude` replaces the exclusion substring; pass `--exclude=` to include all
SAC paths.

When `MERMAID` is set, the script also writes one directory per instrument
under `$MERMAID/countevt/`. Each directory contains one `<COLUMN>.txt` file for
every count column in the table. Each file lists the basenames contributing to
that count, one per line; empty columns have empty files. Event columns list EVT
basenames, and `SAC_NOEVT` columns list SAC basenames.

### reconcile_server.py

Conservatively reconcile multiple MERMAID server trees into a single flat
processing archive.

Default inputs are `$MERMAID/legacy/servers` and `$MERMAID/servers`. Both roots
use the same recursive traversal, visiting subdirectories in alphabetical order
and printing every visited directory. Eligible files directly in either root
are included too. The reconciled archive is `$MERMAID/server`. Explicit `--src`
options replace the default inputs.

Directory exclusions apply at every depth beneath each source or destination
root: names starting with `.` (including `.git`), and the exact names `tools`,
`__pycache__`, `_runs`, and `logs`. These directories and their entire subtrees are
neither scanned nor printed. The reconciliation report lists these exceptions
under its ignore policy. Source-status reports include Git repositories found
within the scanned source trees, including the legacy repositories.

Features:

- Groups files by basename across multiple source trees
- Copies byte-identical binary files and sources that exactly extend the destination
- Merges compatible text records
- Detects conflicting records requiring manual review
- Generates reconciliation, review, and source-status reports
- Never silently overwrites conflicting content

Example:

```bash
scripts/reconcile_server.py --dry-run

scripts/reconcile_server.py \
    --src "$MERMAID/legacy/servers/princeton" \
    --src "$MERMAID/legacy/servers/jamstec" \
    --src "$MERMAID/servers" \
    --dest "$MERMAID/server"
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

Combined family views remain at the output root and include the instrument ID.
The renderer also mirrors each instrument directory below the output root,
with one family file per input family; those float-specific lines omit the
redundant instrument ID.

## Philosophy

These scripts prioritize:

- Conservative data handling
- Explicit review of conflicts
- Reproducibility
- Minimal dependencies
- Preservation of original source data

Developed and maintained by [Bathymetrix®](https://bathymetrix.com).

© 2026 Bathymetrix, LLC

Licensed under the MIT License.
