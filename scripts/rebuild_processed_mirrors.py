#!/usr/bin/env python3
"""Rebuild processed mirrors using automaid's shared mirror utility."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


REBUILD_PROCESSED_MIRRORS_VERSION = "0.5.0"

# Import utils in a separate interpreter: it loads automaid's scientific
# dependencies, which are not required by the other mermaid-scripts utilities.
_REBUILD_COMMAND = """\
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, sys.argv[1])
try:
    from utils import (
        make_processed_read_only,
        rebuild_processed_mirrors,
        version as automaid_version,
    )
except ImportError as error:
    raise SystemExit(
        f"Cannot import automaid's mirror utility: {error}. "
        "Run with automaid's dependencies installed in its .venv or the active Python environment."
    ) from error
try:
    provenance = json.dumps({
        "automaid_version": automaid_version,
        "cli_version": sys.argv[4],
        "source_directory": sys.argv[2],
        "source_git_commit": sys.argv[5] or None,
    }, indent=2) + "\\n"
    rebuild_processed_mirrors(sys.argv[2], sys.argv[3])
    for name in ("metadata", "waveforms"):
        directory = Path(sys.argv[3]) / name
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".provenance-")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(provenance)
            os.replace(temporary, directory / "provenance.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
    make_processed_read_only(sys.argv[2])
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


def source_git_commit(processed_dir: Path) -> str | None:
    """Require a clean owning Git worktree and return its HEAD, if available."""
    if not processed_dir.is_dir():
        raise ValueError(f"Processed directory does not exist: {processed_dir}")
    command = ["git", "--no-optional-locks", "-C", str(processed_dir)]
    environment = {**os.environ, "LC_ALL": "C"}
    repository = subprocess.run(
        [*command, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, env=environment,
    )
    if repository.returncode:
        if "not a git repository" in repository.stderr:
            return None
        raise ValueError(f"Cannot inspect source Git repository: {repository.stderr.strip()}")

    status = subprocess.run(
        [*command, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"],
        capture_output=True, text=True, env=environment,
    )
    if status.returncode:
        raise ValueError(f"Cannot check source Git status: {status.stderr.strip()}")
    if status.stdout:
        raise ValueError(
            f"Source repository must be clean: {repository.stdout.strip()}\n"
            f"{status.stdout.rstrip()}"
        )

    commit = subprocess.run(
        [*command, "rev-parse", "--verify", "--quiet", "HEAD"],
        capture_output=True, text=True, env=environment,
    )
    if commit.returncode not in (0, 1):
        raise ValueError(f"Cannot read source Git commit: {commit.stderr.strip()}")
    return commit.stdout.strip() or None


def rebuild_processed_mirrors(processed_dir: Path, output_dir: Path) -> None:
    """Check source cleanliness, rebuild mirrors, record provenance, and protect sources."""
    processed_dir = processed_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    commit = source_git_commit(processed_dir)
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
            str(processed_dir), str(output_dir),
            REBUILD_PROCESSED_MIRRORS_VERSION, commit or "",
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
