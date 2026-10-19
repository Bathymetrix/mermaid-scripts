#!/usr/bin/env python3
"""Rebuild flat waveform and metadata symlink mirrors from processed files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


REBUILD_PROCESSED_MIRRORS_VERSION = "0.1.0"
MIRROR_DIRECTORIES = (
    "waveforms/sac",
    "waveforms/mseed",
    "metadata/geocsv",
    "metadata/gps",
)


def parse_args() -> argparse.Namespace:
    root = Path(os.environ.get("MERMAID") or "~/mermaid").expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-v", "--version", action="version",
        version=f"%(prog)s {REBUILD_PROCESSED_MIRRORS_VERSION}",
    )
    parser.add_argument(
        "-p", "--processed-dir", type=Path, default=root / "processed",
        help="Source archive (default: $MERMAID/processed, or ~/mermaid/processed).",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=root,
        help="Root for waveforms/ and metadata/ (default: $MERMAID, or ~/mermaid).",
    )
    return parser.parse_args()


def raise_walk_error(error: OSError) -> None:
    """Abort on an unreadable source subtree rather than build a partial mirror."""
    raise error


def discover_sources(
    processed_dir: Path, output_dir: Path,
) -> dict[str, dict[str, Path]]:
    """Collect all link names before changing any destination."""
    if not processed_dir.is_dir():
        raise ValueError(f"Processed directory does not exist: {processed_dir}")
    sources: dict[str, dict[str, Path]] = {name: {} for name in MIRROR_DIRECTORIES}
    destinations = {output_dir / name for name in MIRROR_DIRECTORIES}
    for destination in destinations:
        if processed_dir.is_relative_to(destination.resolve()):
            raise ValueError(f"Source archive is inside a mirror: {destination}")

    for directory, subdirectories, filenames in os.walk(
        processed_dir, onerror=raise_walk_error,
    ):
        directory = Path(directory)
        # Permit outputs under processed/, without rediscovering generated links.
        subdirectories[:] = sorted(
            name for name in subdirectories
            if (directory / name).resolve() not in destinations
        )
        for filename in sorted(filenames):
            source = directory / filename
            link_name = filename
            if source.suffix == ".sac":
                mirror = "waveforms/sac"
            elif source.suffix == ".mseed":
                mirror = "waveforms/mseed"
            elif filename.startswith("geo_") and source.suffix == ".csv":
                mirror = "metadata/geocsv"
            elif filename in {"gps.txt", "gps.csv"}:
                mirror = "metadata/gps"
            else:
                continue
            if not source.is_file():
                continue
            if mirror.startswith("metadata/"):
                relative_parts = source.relative_to(processed_dir).parts
                if len(relative_parts) < 2:
                    raise ValueError(f"Metadata has no instrument directory: {source}")
                # The first directory below processed/ is the instrument serial.
                link_name = f"{relative_parts[0]}-{filename}"
            previous_source = sources[mirror].get(link_name)
            if previous_source is not None:
                raise ValueError(
                    f"Multiple files share {mirror}/{link_name}: "
                    f"{previous_source} and {source}"
                )
            sources[mirror][link_name] = source
    return sources


def rebuild_processed_mirrors(
    processed_dir: Path, output_dir: Path,
) -> dict[str, int]:
    """Replace links in all four mirrors, refusing to remove non-symlink data."""
    processed_dir = processed_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    sources = discover_sources(processed_dir, output_dir)

    # Preflight every destination before removing any previous links.
    for mirror in sources:
        destination = output_dir / mirror
        if destination.is_symlink():
            raise ValueError(f"Mirror directory must not be a symlink: {destination}")
        if destination.exists():
            if not destination.is_dir():
                raise ValueError(f"Mirror path is not a directory: {destination}")
            for entry in destination.iterdir():
                if not entry.is_symlink():
                    raise ValueError(f"Refusing to remove non-symlink: {entry}")

    counts: dict[str, int] = {}
    for mirror, files in sources.items():
        destination = output_dir / mirror
        destination.mkdir(parents=True, exist_ok=True)
        for entry in destination.iterdir():
            entry.unlink()
        for filename, source in files.items():
            (destination / filename).symlink_to(source)
        counts[mirror] = len(files)
    return counts


def main() -> None:
    args = parse_args()
    try:
        counts = rebuild_processed_mirrors(args.processed_dir, args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    for mirror, count in counts.items():
        print(f"{args.output_dir.expanduser().resolve() / mirror}: {count} symlinks")


if __name__ == "__main__":
    main()
