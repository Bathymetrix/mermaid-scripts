#!/usr/bin/env python3
"""Rebuild processed mirrors using automaid's shared mirror utility."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


REBUILD_PROCESSED_MIRRORS_VERSION = "0.3.0"

# Import utils in a separate interpreter: it loads automaid's scientific
# dependencies, which are not required by the other mermaid-scripts utilities.
_REBUILD_COMMAND = """\
import sys
sys.path.insert(0, sys.argv[1])
try:
    from utils import rebuild_processed_mirrors
except ImportError as error:
    raise SystemExit(
        f"Cannot import automaid's mirror utility: {error}. "
        "Run with automaid's dependencies installed in its .venv or the active Python environment."
    ) from error
try:
    rebuild_processed_mirrors(sys.argv[2], sys.argv[3])
except (OSError, ValueError) as error:
    raise SystemExit(str(error)) from error
"""


def mermaid_root() -> Path:
    return Path(os.environ.get("MERMAID") or "~/mermaid").expanduser()


def automaid_root() -> Path:
    """Locate the automaid checkout, conventionally beside mermaid-scripts."""
    return Path(
        os.environ.get("AUTOMAID") or Path(__file__).resolve().parents[2] / "automaid"
    ).expanduser().resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-v", "--version", action="version",
        version=f"%(prog)s {REBUILD_PROCESSED_MIRRORS_VERSION}",
    )
    parser.add_argument(
        "-p", "--processed-dir", type=Path, default=None,
        help="Source archive (default: $MERMAID/processed, or ~/mermaid/processed).",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=None,
        help="Override the mirror root (default: $MERMAID, or processed-dir for custom input).",
    )
    return parser.parse_args()


def rebuild_processed_mirrors(processed_dir: Path, output_dir: Path) -> None:
    """Delegate rebuilding to automaid without importing its processing entry point."""
    automaid_dir = automaid_root()
    scripts_dir = automaid_dir / "scripts"
    if not (scripts_dir / "utils.py").is_file():
        raise FileNotFoundError(
            f"automaid utility not found: {scripts_dir / 'utils.py'}. "
            "Set AUTOMAID to the automaid checkout root."
        )
    python = automaid_dir / ".venv/bin/python"
    if not python.is_file():
        python = Path(sys.executable)
    subprocess.run(
        [
            str(python), "-B", "-c", _REBUILD_COMMAND, str(scripts_dir),
            str(processed_dir.expanduser().resolve()),
            str(output_dir.expanduser().resolve()),
        ],
        check=True,
    )


def main() -> None:
    args = parse_args()
    root = mermaid_root()
    requested_processed_dir = args.processed_dir
    processed_dir = (
        requested_processed_dir.expanduser()
        if requested_processed_dir is not None
        else root / "processed"
    )

    if args.output_dir is not None:
        output_dir = args.output_dir
    elif (
        requested_processed_dir is None
        or requested_processed_dir == Path("processed")
        or processed_dir.resolve() == (root / "processed").resolve()
    ):
        output_dir = root
    else:
        output_dir = processed_dir

    try:
        rebuild_processed_mirrors(processed_dir, output_dir)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Rebuilt processed mirrors under {output_dir.expanduser().resolve()}")


if __name__ == "__main__":
    main()
