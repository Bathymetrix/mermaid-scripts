#!/usr/bin/env python3
"""Report EVT coverage of processed MERMAID SAC files by instrument."""

from __future__ import annotations

import argparse
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


INSTRUMENT_DIRECTORY = re.compile(r".*[0-9]-[A-Z]-[0-9].*")
EXCEPTION_CATEGORIES = (
    "PRELIM_EVT",
    "EVT_NO_SAC",
    "REVIEWED_UNCLASSIFIED",
    "DUPLICATE_EVT",
)
COUNT_COLUMNS = (
    "EVT_REV",
    "EVT_ID",
    "EVT_ID_DET",
    "EVT_ID_REQ",
    "EVT_NOID",
    "EVT_NOID_DET",
    "EVT_NOID_REQ",
    "EVT_UNREV",
    "EVT_UNREV_DET",
    "EVT_UNREV_REQ",
    "SAC_NOEVT",
    "SAC_NOEVT_DET",
    "SAC_NOEVT_REQ",
)


@dataclass(frozen=True)
class SacFile:
    """A SAC file and the instrument and acquisition type it represents."""

    path: Path
    instrument: str
    kind: str


def default_sacdir() -> Path | None:
    """Return the conventional processed directory when MERMAID is set."""
    mermaid_root = os.environ.get("MERMAID")
    return Path(mermaid_root).expanduser() / "processed_everyone" if mermaid_root else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-s", "--sacdir", type=Path, default=default_sacdir(),
        help="Processed SAC archive root (default: $MERMAID/processed_everyone).",
    )
    parser.add_argument("-e", "--evtdir", type=Path, required=True, help="Event archive root.")
    args = parser.parse_args()
    if args.sacdir is None:
        parser.error("--sacdir is required when the MERMAID environment variable is unset")
    return args


def instrument_directories(sacdir: Path) -> list[Path]:
    """Return immediate instrument directories in countsac.py order."""
    return sorted(
        (path for path in sacdir.expanduser().iterdir() if path.is_dir()
         and INSTRUMENT_DIRECTORY.fullmatch(path.name)),
        key=lambda path: path.name,
    )


def sac_kind(path: Path) -> str:
    """Return the acquisition type encoded by a SAC filename."""
    if ".DET." in str(path):
        return "DET"
    if ".REQ." in str(path):
        return "REQ"
    raise ValueError(f"SAC file is neither DET nor REQ: {path}")


def evt_basename(sac_path: Path) -> str:
    """Map a SAC basename to its EVT basename by replacing its final suffix."""
    return f"{sac_path.name[:-4]}.evt"


def sac_inventory(sacdir: Path) -> tuple[list[str], dict[str, SacFile]]:
    """Build the authoritative, uniquely named SAC inventory."""
    instruments: list[str] = []
    inventory: dict[str, SacFile] = {}
    for directory in instrument_directories(sacdir):
        instruments.append(directory.name)
        for path in sorted(candidate for candidate in directory.rglob("*.sac") if candidate.is_file()):
            name = evt_basename(path)
            if name in inventory:
                raise ValueError(f"SAC basename occurs more than once: {name}")
            inventory[name] = SacFile(path, directory.name, sac_kind(path))
    return instruments, inventory


def event_files(evtdir: Path) -> list[Path]:
    """Return EVT files from the reviewed and unreviewed event trees."""
    files: list[Path] = []
    for directory in (evtdir / "reviewed", evtdir / "unreviewed"):
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*.evt") if path.is_file())
    return sorted(files)


def is_prelim(path: Path) -> bool:
    """Return whether any portion of an EVT path is marked prelim."""
    return "prelim" in str(path).lower()


def event_category(path: Path, evtdir: Path) -> str | None:
    """Return the clean EVT category for *path*, or None when unclassified."""
    reviewed = evtdir / "reviewed"
    if path.is_relative_to(evtdir / "reviewed" / "identified"):
        return "ID"
    if path.is_relative_to(evtdir / "reviewed" / "unidentified"):
        return "NOID"
    if path.is_relative_to(reviewed):
        return None
    if path.is_relative_to(evtdir / "unreviewed"):
        return "UNREV"
    return None


def empty_counts() -> Counter[str]:
    """Return a counter containing every report column."""
    return Counter({column: 0 for column in COUNT_COLUMNS})


def check_counts(label: str, counts: Counter[str]) -> None:
    """Verify the relationships represented by a clean table row."""
    for total, det, req in (
        ("EVT_ID", "EVT_ID_DET", "EVT_ID_REQ"),
        ("EVT_NOID", "EVT_NOID_DET", "EVT_NOID_REQ"),
        ("EVT_UNREV", "EVT_UNREV_DET", "EVT_UNREV_REQ"),
        ("SAC_NOEVT", "SAC_NOEVT_DET", "SAC_NOEVT_REQ"),
    ):
        if counts[total] != counts[det] + counts[req]:
            raise ValueError(f"{total} does not sum as expected for {label}")
    if counts["EVT_REV"] != counts["EVT_ID"] + counts["EVT_NOID"]:
        raise ValueError(f"EVT_REV does not sum as expected for {label}")


def count_evt(sacdir: Path, evtdir: Path) -> list[str]:
    """Return the complete SAC/EVT coverage report."""
    instruments, inventory = sac_inventory(sacdir)
    counts = {instrument: empty_counts() for instrument in instruments}
    exceptions: dict[str, list[Path]] = {category: [] for category in EXCEPTION_CATEGORIES[:-1]}
    nonprelim_by_name: dict[str, list[Path]] = defaultdict(list)

    events = event_files(evtdir)
    for path in events:
        if is_prelim(path):
            exceptions["PRELIM_EVT"].append(path)
        else:
            nonprelim_by_name[path.name].append(path)

    duplicates = {name: paths for name, paths in nonprelim_by_name.items() if len(paths) > 1}
    for name, paths in nonprelim_by_name.items():
        sac = inventory.get(name)
        for path in paths:
            category = event_category(path, evtdir)
            if sac is None:
                exceptions["EVT_NO_SAC"].append(path)
            if category is None and path.is_relative_to(evtdir / "reviewed"):
                exceptions["REVIEWED_UNCLASSIFIED"].append(path)
        if name in duplicates:
            continue
        path = paths[0]
        category = event_category(path, evtdir)
        if sac is None or category is None:
            continue

        row = counts[sac.instrument]
        if category == "ID":
            row["EVT_ID"] += 1
            row[f"EVT_ID_{sac.kind}"] += 1
            row["EVT_REV"] += 1
        elif category == "NOID":
            row["EVT_NOID"] += 1
            row[f"EVT_NOID_{sac.kind}"] += 1
            row["EVT_REV"] += 1
        else:
            row["EVT_UNREV"] += 1
            row[f"EVT_UNREV_{sac.kind}"] += 1

    all_event_names = {path.name for path in events}
    for name, sac in inventory.items():
        if name not in all_event_names:
            row = counts[sac.instrument]
            row["SAC_NOEVT"] += 1
            row[f"SAC_NOEVT_{sac.kind}"] += 1

    duplicate_details = [
        (name, sorted(paths, key=lambda path: str(path.relative_to(evtdir))))
        for name, paths in sorted(duplicates.items())
    ]
    for instrument, row in counts.items():
        check_counts(instrument, row)
    total = empty_counts()
    for row in counts.values():
        total.update(row)
    check_counts("TOTAL", total)

    header = (
        f"{'SERIAL':>14s}  EVT_REV | EVT_ID EVT_ID_DET EVT_ID_REQ | "
        "EVT_NOID EVT_NOID_DET EVT_NOID_REQ | EVT_UNREV EVT_UNREV_DET EVT_UNREV_REQ | "
        "SAC_NOEVT SAC_NOEVT_DET SAC_NOEVT_REQ"
    )
    lines = [header]
    for instrument in instruments:
        lines.append(format_row(instrument, counts[instrument]))
    lines.extend(["_" * len(header), format_row("TOTAL", total), "", "EXCEPTIONS", "----------"])
    exception_counts = {
        **{category: len(paths) for category, paths in exceptions.items()},
        "DUPLICATE_EVT": len(duplicate_details),
    }
    lines.extend(f"{category:<25s} {exception_counts[category]:5d}" for category in EXCEPTION_CATEGORIES)

    for category in EXCEPTION_CATEGORIES[:-1]:
        paths = exceptions[category]
        if paths:
            lines.extend(["", f"{category} ({len(paths)})"])
            lines.extend(f"  {path.relative_to(evtdir)}" for path in paths)
    if duplicate_details:
        lines.extend(["", f"DUPLICATE_EVT ({len(duplicate_details)})"])
        for name, paths in duplicate_details:
            lines.append(f"  {name}")
            lines.extend(f"    {path.relative_to(evtdir)}" for path in paths)
    return lines


def format_row(label: str, counts: Counter[str]) -> str:
    """Format one fixed-width table row."""
    groups = (
        ("EVT_REV",), ("EVT_ID", "EVT_ID_DET", "EVT_ID_REQ"),
        ("EVT_NOID", "EVT_NOID_DET", "EVT_NOID_REQ"),
        ("EVT_UNREV", "EVT_UNREV_DET", "EVT_UNREV_REQ"),
        ("SAC_NOEVT", "SAC_NOEVT_DET", "SAC_NOEVT_REQ"),
    )
    values = (" ".join(f"{counts[column]:6d}" for column in group) for group in groups)
    return f"{label:>14s}  " + " | ".join(values)


def main() -> None:
    args = parse_args()
    print("\n".join(count_evt(args.sacdir, args.evtdir)))


if __name__ == "__main__":
    main()
