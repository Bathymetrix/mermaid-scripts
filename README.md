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

Rebuild flat waveform and metadata symlink mirrors by calling
`automaid/scripts/utils.py:rebuild_processed_mirrors`. This command and
automaid's processing workflow use the same implementation; file selection,
link naming, collision checks, and mirror replacement are owned by automaid.
The current shared utility produces six mirrors:

| Destination | Source files | Link names |
| --- | --- | --- |
| `waveforms/sac/` | `*.sac` | Original basename |
| `waveforms/mseed/` | `*.mseed` | Original basename |
| `metadata/geocsv/` | `geo_DET_REQ.csv` | `<instrument>.geocsv` |
| `metadata/gps/` | `gps.txt`, `gps.csv` | `<instrument>.gps.txt`, `<instrument>.gps.csv` |
| `metadata/automaid/` | `automaid_metadata_*.csv` | `<instrument>.<basename>` |
| `metadata/mseed2sac/` | `mseed2sac_metadata_*.csv` | `<instrument>.<basename>` |

```bash
scripts/rebuild_processed_mirrors.py
scripts/rebuild_processed_mirrors.py --processed-dir /path/to/processed --output-dir /path/to/mirrors
```

The automaid checkout is located through `$AUTOMAID`, falling back to a sibling
`automaid/` checkout beside `mermaid-scripts/`. The wrapper uses automaid's
`.venv/bin/python` when present, otherwise the interpreter running the wrapper.
That interpreter must provide automaid's dependencies, including NumPy, Plotly,
and ObsPy, because importing `utils.py` loads them. The wrapper imports only
the utility module and does not run automaid's processing entry point.

The default source is `$MERMAID/processed`, falling back to
`~/mermaid/processed` when `MERMAID` is unset. The default mirror root is
`$MERMAID` (or `~/mermaid`) when `--processed-dir` is omitted, is the literal
`processed`, or resolves to the default source directory. For other source
paths, mirrors are created inside the specified processed directory.
`--output-dir` overrides the mirror root in every case. These path rules are
unchanged from version 0.2.0.

The shared utility traverses sources recursively and takes the instrument ID
from the first directory below the processed root. Each run replaces all links
in its six mirror directories, including stale or broken links, with absolute
links to source paths. Matching is case-sensitive and includes all cycles.
Duplicate link names, a missing source directory, or non-symlink contents in a
mirror abort the run before existing links are removed. Mirror directories
themselves must not be symlinks. Parent-level `.git/` directories are preserved;
source files are never copied or modified.

The CLI wrapper requires Git to inspect the source directory. If the source
belongs to a Git working tree, the entire owning repository must be clean:
no staged or unstaged changes, deleted files, untracked files, or dirty
submodules. Files ignored by Git do not count as untracked files. The check
runs before rebuilding or updating provenance, with no special exemptions for
mirror outputs. When outputs are inside the source repository, they must also
satisfy its normal tracking or ignore policy on subsequent runs. Sources
outside Git repositories are allowed. This cleanliness requirement applies
only to this wrapper; automaid's processing workflow is unchanged.

After a successful rebuild, the wrapper writes identical `provenance.json`
files in the output root's `metadata/` and `waveforms/` directories. Each file
is replaced on each successful run and contains:

| Field | Meaning |
| --- | --- |
| `automaid_version` | Version reported by the automaid utility loaded for this rebuild |
| `cli_version` | Version of `rebuild_processed_mirrors.py` |
| `source_directory` | Absolute, symlink-resolved path to the byte-owning processed archive |
| `source_git_commit` | Full HEAD commit ID of the source's owning repository, or `null` outside Git or before its first commit |

Each provenance file is replaced atomically after rebuilding, rather than
appended as a history log. A rejected source or failed shared rebuild leaves
previous provenance unchanged.

After rebuilding and writing both provenance files, the wrapper calls
`utils.make_processed_read_only(processed_dir)`. This removes owner, group,
and other write permissions from all non-symlink files and directories in the
canonical processed tree, including its `.git/` directory when present.
Symlinks are not followed. Canonical files are therefore read-only through
their mirror links as well. Mirror directories outside the processed tree
remain writable for subsequent rebuilds. If protection fails, the command
exits unsuccessfully without printing its completion message.

Version 0.5.0 adds the final processed-tree protection step. Mirror selection,
naming, and permission handling remain delegated to automaid. The command
prints a completion message after success; the shared utility does not
return per-mirror counts.

### countsac.py

Report the total number of processed lower-case `.sac` files for each
instrument, split into detected (`.DET.`) and requested (`.REQ.`) waveforms.
The report includes the latest UTC start date from each class, read from the
SAC filename. By default it reads `$MERMAID/processed`.

```bash
scripts/countsac.py
scripts/countsac.py --sacdir "$MERMAID/processed"
scripts/countsac.py --sacdir "$MERMAID/processed" --exclude=OtherSubstring
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
    --sacdir "$MERMAID/processed" \
    --evtdir "$MERMAID/events" \
    --exclude=OtherSubstring
```

`--sacdir` and `--evtdir` default to `$MERMAID/processed` and
`$MERMAID/events`, respectively, when `MERMAID` is set. The event
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
