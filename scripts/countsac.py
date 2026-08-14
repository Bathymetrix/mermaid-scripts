#!/usr/bin/env python3
"""Print MERMAID processed SAC file dates and counts.

This is a command-line implementation of ``countsac.m``.  A MERMAID SAC
filename begins with its UTC start time (``YYYYMMDDTHHMMSS``); that timestamp
is used to report the latest DET and REQ waveform for each instrument.
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path


INSTRUMENT_DIRECTORY = re.compile(r".*[0-9]-[A-Z]-[0-9].*")
SAC_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"
COUNTSAC_VERSION = "0.1.0"


def default_processed_dir() -> Path | None:
    """Return the conventional processed directory when MERMAID is set."""
    mermaid_root = os.environ.get("MERMAID")
    return Path(mermaid_root).expanduser() / "processed_everyone" if mermaid_root else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {COUNTSAC_VERSION}"
    )
    parser.add_argument(
        "procdir",
        nargs="?",
        type=Path,
        default=default_processed_dir(),
        help="Processed directory (default: $MERMAID/processed_everyone).",
    )
    parser.add_argument(
        "excl",
        nargs="?",
        help="Optional substring: SAC paths containing it are excluded.",
    )
    args = parser.parse_args()
    if args.procdir is None:
        parser.error("procdir is required when the MERMAID environment variable is unset")
    return args


def instrument_directories(procdir: Path) -> list[Path]:
    """Return immediate instrument directories in MATLAB ``dir`` name order."""
    return sorted(
        (
            path
            for path in procdir.expanduser().iterdir()
            if path.is_dir() and INSTRUMENT_DIRECTORY.fullmatch(path.name)
        ),
        key=lambda path: path.name,
    )


def sac_files(directory: Path, exclusion: str | None = None) -> list[Path]:
    """Return matching ``.sac`` files recursively, optionally excluding paths."""
    files = sorted(path for path in directory.rglob("*.sac") if path.is_file())
    if exclusion:
        files = [path for path in files if exclusion not in str(path)]
    return files


def sac_date(path: Path) -> datetime:
    """Parse the UTC first-sample time encoded in a MERMAID SAC filename."""
    return datetime.strptime(path.name[:15], SAC_TIMESTAMP_FORMAT)


def latest_date(files: Iterable[Path]) -> str:
    """Return a MATLAB ``datestr``-style date, or ``NaT`` for no files."""
    dates = [sac_date(path) for path in files]
    return max(dates).strftime("%d-%b-%Y") if dates else "NaT"


def count_sac(procdir: Path, exclusion: str | None = None) -> list[str]:
    """Return the report lines for processed SAC files below *procdir*."""
    total_sac = total_det = total_req = 0
    lines = ["                   ALL      DET      LAST_DET     REQ       LAST_REQ"]

    for directory in instrument_directories(procdir):
        files = sac_files(directory, exclusion)
        det_files = [path for path in files if ".DET." in str(path)]
        req_files = [path for path in files if ".REQ." in str(path)]

        if len(det_files) + len(req_files) != len(files):
            raise ValueError(f"SAC lists don't sum as expected for {directory}")

        lines.append(
            f"{directory.name:>14s} : {len(files):5d}    {len(det_files):5d}   "
            f"{latest_date(det_files):>11s}   {len(req_files):5d}    "
            f"{latest_date(req_files):>11s}"
        )
        total_sac += len(files)
        total_det += len(det_files)
        total_req += len(req_files)

    lines.extend(
        [
            "____________________________________________________________________",
            f"TOTAL :          {total_sac:5d}    {total_det:5d}                 {total_req:5d}",
        ]
    )
    return lines


def main() -> None:
    args = parse_args()
    print("\n".join(count_sac(args.procdir, args.excl)))


if __name__ == "__main__":
    main()
