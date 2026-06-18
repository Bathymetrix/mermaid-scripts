#!/usr/bin/env python3
"""Conservatively reconcile flat MERMAID server files.

This utility reconciles disparate MERMAID server trees into one flat processing
archive.  It groups source files by basename, copies byte-identical binary
files, merges text records when possible, and reports records needing review.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

RECONCILE_SERVER_VERSION = "0.1.0"

MERMAID_ROOT = Path(os.environ.get("MERMAID", "~/mermaid")).expanduser()
DEFAULT_SOURCES = [
    MERMAID_ROOT / "server",
    MERMAID_ROOT / "server_jamstec",
    MERMAID_ROOT / "server_sustech",
    MERMAID_ROOT / "server_stanford",
    MERMAID_ROOT / "servers",
]
DEFAULT_DEST = MERMAID_ROOT / "server_everyone"

ALL_EXTENSIONS = {
    ".BIN",
    ".LOG",
    ".MER",
    ".S41",
    ".S61",
    ".out",
    ".vit",
}

TEXT_EXTENSIONS = {".LOG", ".MER", ".vit"}
OUT_EXTENSION = ".out"

IGNORE_POLICY = [
    ".cmd intentionally excluded: operational request history, mutable operational/request files, and not part of the flat processing archive",
    "basenames containing ZMODEM",
    "basenames containing nohup",
    "lowercase .log",
    "basenames ending in old immediately before an accepted extension",
    "any file not matching the allowed MERMAID processing extensions",
]

TIMESTAMP_PATTERNS = [
    re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}[:_]\d{2}[:_]\d{2}"),
    re.compile(rb"\d{8}-\d{2}h\d{2}mn\d{2}"),
]
OUT_SESSION_START = re.compile(
    rb"^\*\*\*\d{8}-\d{2}h\d{2}mn\d{2}: sending cmd from "
)


@dataclass(frozen=True)
class Candidate:
    path: Path
    size: int
    is_dest: bool = False


@dataclass(frozen=True)
class Difference:
    left: Path
    right: Path
    left_line_number: int | None
    right_line_number: int | None
    left_line: bytes | None
    right_line: bytes | None


@dataclass(frozen=True)
class Conflict:
    basename: str
    candidates: list[Candidate]
    difference: Difference


@dataclass(frozen=True)
class Record:
    key: tuple[str, bytes]
    line: bytes
    chunk: bytes
    path: Path
    line_number: int
    has_timestamp: bool
    is_dest: bool


@dataclass(frozen=True)
class Resolution:
    action: str
    winner: Candidate | None = None
    merged_content: bytes | None = None
    conflict: Conflict | None = None


@dataclass(frozen=True)
class OutParseResult:
    blocks: list[bytes]
    conflict: Difference | None = None


def should_replace_conflict_reference(
    previous_is_dest: bool, candidate_is_dest: bool
) -> bool:
    return previous_is_dest and not candidate_is_dest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge MERMAID server files into one flat destination."
    )
    parser.add_argument(
        "--src",
        action="append",
        type=Path,
        help="Source directory. May be supplied multiple times.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path(DEFAULT_DEST),
        help=f"Flat destination directory. Default: {DEFAULT_DEST}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and print reports without writing files.",
    )
    return parser.parse_args()


def expand_path(path: Path) -> Path:
    return path.expanduser().resolve()


def is_candidate_file(path: Path) -> bool:
    if "ZMODEM" in path.name or "nohup" in path.name:
        return False
    if path.suffix in {".cmd", ".log"}:
        return False

    suffix = path.suffix
    has_allowed_suffix = suffix in ALL_EXTENSIONS or (
        len(suffix) == 4 and suffix[0] == "." and suffix[1:].isdigit()
    )
    if has_allowed_suffix and path.stem.endswith("old"):
        return False
    return has_allowed_suffix


def is_text_file(basename: str) -> bool:
    return Path(basename).suffix in TEXT_EXTENSIONS


def scan_tree(
    root: Path, *, is_dest: bool, groups: dict[str, list[Candidate]], seen: set[Path]
) -> int:
    """Add candidate files below root and return the number of ignored files."""
    ignored = 0
    if not root.exists():
        return ignored

    if root.is_file():
        files = [root]
    else:
        files = (
            path
            for path in root.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
        )

    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        if not is_candidate_file(path):
            ignored += 1
            continue

        groups[path.name].append(
            Candidate(path=resolved, size=resolved.stat().st_size, is_dest=is_dest)
        )

    return ignored


def read_lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines(keepends=True)


def first_difference(left: Candidate, right: Candidate) -> Difference:
    left_lines = read_lines(left.path)
    right_lines = read_lines(right.path)
    for index, (left_line, right_line) in enumerate(zip(left_lines, right_lines), 1):
        if left_line != right_line:
            return Difference(left.path, right.path, index, index, left_line, right_line)

    line_number = min(len(left_lines), len(right_lines)) + 1
    left_line = left_lines[line_number - 1] if line_number <= len(left_lines) else None
    right_line = right_lines[line_number - 1] if line_number <= len(right_lines) else None
    return Difference(left.path, right.path, line_number, line_number, left_line, right_line)


def find_conflict_pair(candidates: list[Candidate]) -> Difference:
    representatives: list[Candidate] = []
    for candidate in candidates:
        for index, existing in enumerate(representatives):
            if filecmp.cmp(existing.path, candidate.path, shallow=False):
                if should_replace_conflict_reference(
                    existing.is_dest, candidate.is_dest
                ):
                    representatives[index] = candidate
                break
        else:
            representatives.append(candidate)

    for left_index, left in enumerate(representatives):
        for right in representatives[left_index + 1 :]:
            if not filecmp.cmp(left.path, right.path, shallow=False):
                if should_replace_conflict_reference(left.is_dest, right.is_dest):
                    return first_difference(right, left)
                return first_difference(left, right)

    # This should only be reached for unusual duplicate-path or race cases.
    return first_difference(representatives[0], representatives[-1])


def timestamp_key(line: bytes) -> bytes | None:
    for pattern in TIMESTAMP_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(0)
    return None


def record_key(line: bytes) -> tuple[tuple[str, bytes], bool]:
    # Plain telemetry may legitimately have several records per timestamp.
    # REQUEST lines, however, should be unique for a given request timestamp.
    if b"mermaid REQUEST:" in line:
        timestamp = timestamp_key(line)
        if timestamp is not None:
            return ("timestamp", timestamp), True
    return ("line", line), False


def iter_records(candidate: Candidate) -> list[Record]:
    records = []
    pending_blank_lines: list[bytes] = []
    for line_number, line in enumerate(read_lines(candidate.path), 1):
        if not line.strip():
            pending_blank_lines.append(line)
            continue
        key, has_timestamp = record_key(line)
        records.append(
            Record(
                key=key,
                line=line,
                chunk=b"".join(pending_blank_lines) + line,
                path=candidate.path,
                line_number=line_number,
                has_timestamp=has_timestamp,
                is_dest=candidate.is_dest,
            )
        )
        pending_blank_lines = []
    if records and pending_blank_lines:
        records[-1] = replace(
            records[-1], chunk=records[-1].chunk + b"".join(pending_blank_lines)
        )
    return records


def leading_blank_lines(content: bytes) -> list[bytes]:
    lines = []
    for line in content.splitlines(keepends=True):
        if line.strip():
            break
        lines.append(line)
    return lines


def trailing_blank_lines(content: bytes) -> list[bytes]:
    lines = []
    for line in reversed(content.splitlines(keepends=True)):
        if line.strip():
            break
        lines.append(line)
    lines.reverse()
    return lines


def append_text_chunk(output_chunks: list[bytes], chunk: bytes) -> None:
    if not output_chunks:
        output_chunks.append(chunk)
        return

    trailing = trailing_blank_lines(output_chunks[-1])
    leading = leading_blank_lines(chunk)
    if trailing and leading:
        overlap = min(len(trailing), len(leading))
        chunk = b"".join(leading[overlap:]) + chunk[len(b"".join(leading)) :]
    output_chunks.append(chunk)


def same_content_as_dest(content: bytes, candidates: list[Candidate]) -> bool:
    for candidate in candidates:
        if candidate.is_dest and candidate.path.read_bytes() == content:
            return True
    return False


def parse_out_blocks(candidate: Candidate) -> OutParseResult:
    blocks: list[bytes] = []
    current_block: list[bytes] = []

    for line_number, line in enumerate(read_lines(candidate.path), 1):
        if OUT_SESSION_START.match(line):
            if current_block:
                blocks.append(b"".join(current_block))
            current_block = [line]
            continue

        if current_block:
            current_block.append(line)
            continue

        if line.strip():
            return OutParseResult(
                blocks=[],
                conflict=Difference(
                    candidate.path,
                    candidate.path,
                    line_number,
                    line_number,
                    line,
                    line,
                ),
            )

    if current_block:
        blocks.append(b"".join(current_block))

    return OutParseResult(blocks=blocks)


def first_block_difference(
    left_path: Path, right_path: Path, left_block: bytes, right_block: bytes
) -> Difference:
    left_lines = left_block.splitlines(keepends=True)
    right_lines = right_block.splitlines(keepends=True)
    for index, (left_line, right_line) in enumerate(zip(left_lines, right_lines), 1):
        if left_line != right_line:
            return Difference(left_path, right_path, index, index, left_line, right_line)

    line_number = min(len(left_lines), len(right_lines)) + 1
    left_line = left_lines[line_number - 1] if line_number <= len(left_lines) else None
    right_line = right_lines[line_number - 1] if line_number <= len(right_lines) else None
    return Difference(left_path, right_path, line_number, line_number, left_line, right_line)


def resolve_out_group(basename: str, candidates: list[Candidate]) -> Resolution:
    output_blocks: list[bytes] = []
    seen_blocks: set[bytes] = set()
    session_blocks: dict[bytes, tuple[bytes, Candidate]] = {}
    duplicate_seen = False

    for candidate in candidates:
        parsed = parse_out_blocks(candidate)
        if parsed.conflict is not None:
            return Resolution(
                action="conflicts",
                conflict=Conflict(
                    basename=basename,
                    candidates=candidates,
                    difference=parsed.conflict,
                ),
            )

        for block in parsed.blocks:
            session_start = block.splitlines(keepends=True)[0]
            previous_session = session_blocks.get(session_start)
            if previous_session is not None and previous_session[0] != block:
                if should_replace_conflict_reference(
                    previous_session[1].is_dest, candidate.is_dest
                ):
                    difference = first_block_difference(
                        candidate.path,
                        previous_session[1].path,
                        block,
                        previous_session[0],
                    )
                else:
                    difference = first_block_difference(
                        previous_session[1].path,
                        candidate.path,
                        previous_session[0],
                        block,
                    )
                return Resolution(
                    action="conflicts",
                    conflict=Conflict(
                        basename=basename,
                        candidates=candidates,
                        difference=difference,
                    ),
                )
            if previous_session is None or (
                should_replace_conflict_reference(
                    previous_session[1].is_dest, candidate.is_dest
                )
            ):
                session_blocks[session_start] = (block, candidate)

            if block in seen_blocks:
                duplicate_seen = True
                continue
            seen_blocks.add(block)
            output_blocks.append(block)

    merged_content = b"".join(output_blocks)
    if same_content_as_dest(merged_content, candidates):
        return Resolution(action="already_current")

    action = "merged_deduplicated" if duplicate_seen else "merged_disjoint"
    return Resolution(action=action, merged_content=merged_content)


def resolve_text_group(basename: str, candidates: list[Candidate]) -> Resolution:
    """Merge text records by timestamp key when obvious, else by full line."""
    output_records: list[Record] = []
    seen_exact_lines: dict[bytes, set[Path]] = defaultdict(set)
    timestamp_records: dict[tuple[str, bytes], list[Record]] = defaultdict(list)
    duplicate_seen = False

    for candidate in candidates:
        for record in iter_records(candidate):
            previous_line_paths = seen_exact_lines[record.line]

            if record.has_timestamp:
                # Regression guard: one file may contain two different records
                # for the same timestamp. Preserve same-file repeats; only
                # different candidate files can conflict.
                for previous in timestamp_records[record.key]:
                    if previous.path == record.path:
                        continue
                    if previous.line != record.line:
                        if should_replace_conflict_reference(
                            previous.is_dest, record.is_dest
                        ):
                            difference = Difference(
                                record.path,
                                previous.path,
                                record.line_number,
                                previous.line_number,
                                record.line,
                                previous.line,
                            )
                        else:
                            difference = Difference(
                                previous.path,
                                record.path,
                                previous.line_number,
                                record.line_number,
                                previous.line,
                                record.line,
                            )
                        return Resolution(
                            action="conflicts",
                            conflict=Conflict(
                                basename=basename,
                                candidates=candidates,
                                difference=difference,
                            ),
                        )

                if previous_line_paths and record.path not in previous_line_paths:
                    duplicate_seen = True
                    for index, previous in enumerate(timestamp_records[record.key]):
                        if (
                            previous.line == record.line
                            and should_replace_conflict_reference(
                                previous.is_dest, record.is_dest
                            )
                        ):
                            timestamp_records[record.key][index] = record
                    previous_line_paths.add(record.path)
                    continue

                timestamp_records[record.key].append(record)
            elif previous_line_paths and record.path not in previous_line_paths:
                duplicate_seen = True
                previous_line_paths.add(record.path)
                continue

            previous_line_paths.add(record.path)
            output_records.append(record)

    if not output_records:
        return Resolution(
            action="conflicts",
            conflict=Conflict(
                basename=basename,
                candidates=candidates,
                difference=find_conflict_pair(candidates),
            ),
        )

    if output_records and all(record.has_timestamp for record in output_records):
        output_records.sort(
            key=lambda record: (record.key, str(record.path), record.line_number)
        )

    output_chunks: list[bytes] = []
    for record in output_records:
        append_text_chunk(output_chunks, record.chunk)
    merged_content = b"".join(output_chunks)
    if same_content_as_dest(merged_content, candidates):
        return Resolution(action="already_current")

    action = "merged_deduplicated" if duplicate_seen else "merged_disjoint"
    return Resolution(action=action, merged_content=merged_content)


def resolve_binary_group(basename: str, candidates: list[Candidate]) -> Resolution:
    dest_candidates = [candidate for candidate in candidates if candidate.is_dest]

    if len(candidates) == 1:
        only = candidates[0]
        if only.is_dest:
            return Resolution(action="already_current")
        return Resolution(action="copied_single", winner=only)

    first = candidates[0]
    if all(filecmp.cmp(first.path, candidate.path, shallow=False) for candidate in candidates[1:]):
        if dest_candidates:
            return Resolution(action="already_current")
        return Resolution(action="copied_identical", winner=first)

    return Resolution(
        action="conflicts",
        conflict=Conflict(
            basename=basename,
            candidates=candidates,
            difference=find_conflict_pair(candidates),
        ),
    )


def resolve_group(basename: str, candidates: list[Candidate]) -> Resolution:
    if len(candidates) == 1:
        only = candidates[0]
        if only.is_dest:
            return Resolution(action="already_current")
        return Resolution(action="copied_single", winner=only)

    first = candidates[0]
    if all(filecmp.cmp(first.path, candidate.path, shallow=False) for candidate in candidates[1:]):
        if any(candidate.is_dest for candidate in candidates):
            return Resolution(action="already_current")
        return Resolution(action="copied_identical", winner=first)

    if Path(basename).suffix == OUT_EXTENSION:
        return resolve_out_group(basename, candidates)
    if is_text_file(basename):
        return resolve_text_group(basename, candidates)
    return resolve_binary_group(basename, candidates)


def candidate_sort_key(candidate: Candidate) -> tuple[bool, str]:
    return (candidate.is_dest, str(candidate.path))


def preview_line(line: bytes | None) -> str:
    if line is None:
        return "<missing>"
    text = repr(line)
    if len(text) <= 200:
        return text
    return text[:197] + "..."


def write_file_if_changed(src: Path, dest: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    if dest.exists() and filecmp.cmp(src, dest, shallow=False):
        return
    shutil.copy2(src, dest)


def write_bytes_if_changed(content: bytes, dest: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    if dest.exists() and dest.read_bytes() == content:
        return
    dest.write_bytes(content)


def format_counts(counts: Counter[str]) -> str:
    keys = [
        "basenames_considered",
        "copied_single",
        "copied_identical",
        "merged_disjoint",
        "merged_deduplicated",
        "already_current",
        "conflicts",
        "ignored_files",
    ]
    return "\n".join(f"{key}: {counts[key]}" for key in keys)


def build_report(
    *,
    sources: list[Path],
    dest: Path,
    dry_run: bool,
    counts: Counter[str],
) -> str:
    lines = [
        "MERMAID server reconciliation report",
        f"version: {RECONCILE_SERVER_VERSION}",
        f"timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"dry_run: {dry_run}",
        "",
        "source directories:",
    ]
    lines.extend(f"  {source}" for source in sources)
    lines.extend(
        [
            "",
            f"destination directory: {dest}",
            "",
            "ignore policy:",
        ]
    )
    lines.extend(f"  - {rule}" for rule in IGNORE_POLICY)
    lines.extend(["", "counts:", format_counts(counts), ""])
    return "\n".join(lines)


def run_git(source: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(source), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def source_git_log(sources: list[Path]) -> str:
    sections = []
    for source in sources:
        lines = [str(source)]
        inside_work_tree = run_git(source, ["rev-parse", "--is-inside-work-tree"])
        if inside_work_tree.returncode != 0 or inside_work_tree.stdout.strip() != "true":
            lines.extend(
                [
                    "Commit: <not a git repository>",
                    "Status:",
                    "<not a git repository>",
                ]
            )
            sections.append("\n".join(lines))
            continue

        commit = run_git(source, ["rev-parse", "HEAD"])
        if commit.returncode == 0:
            lines.append(f"Commit: {commit.stdout.strip()}")
        else:
            lines.append(f"Commit: <git error: {commit.stderr.strip()}>")

        status = run_git(source, ["status"])
        lines.append("Status:")
        if status.returncode == 0:
            lines.append(status.stdout.rstrip())
        else:
            lines.append(f"<git error: {status.stderr.strip()}>")

        sections.append("\n".join(lines))

    return "\n_____________________________________\n".join(sections) + "\n"


def build_review_report(conflicts: list[Conflict]) -> str:
    if not conflicts:
        return "No records need review.\n"

    lines = ["MERMAID server reconciliation review", ""]
    for conflict in conflicts:
        diff = conflict.difference
        lines.extend(
            [
                f"basename: {conflict.basename}",
                "candidates:",
            ]
        )
        for candidate in sorted(conflict.candidates, key=candidate_sort_key):
            marker = " [destination]" if candidate.is_dest else " [source]"
            lines.append(f"  {candidate.path} ({candidate.size} bytes){marker}")
        lines.extend(
            [
                "first conflicting records examined:",
                f"  left:  {diff.left}:{diff.left_line_number}",
                f"  right: {diff.right}:{diff.right_line_number}",
                f"left line:  {preview_line(diff.left_line)}",
                f"right line: {preview_line(diff.right_line)}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    sources = [expand_path(path) for path in (args.src or map(Path, DEFAULT_SOURCES))]
    dest = expand_path(args.dest)

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[Candidate]] = defaultdict(list)
    seen: set[Path] = set()
    counts: Counter[str] = Counter()

    for source in sources:
        counts["ignored_files"] += scan_tree(
            source, is_dest=False, groups=groups, seen=seen
        )

    counts["ignored_files"] += scan_tree(dest, is_dest=True, groups=groups, seen=seen)
    counts["basenames_considered"] = len(groups)

    conflicts: list[Conflict] = []

    for basename in sorted(groups):
        candidates = groups[basename]
        resolution = resolve_group(basename, candidates)
        counts[resolution.action] += 1

        if resolution.conflict is not None:
            conflicts.append(resolution.conflict)
            continue

        if resolution.winner is not None:
            write_file_if_changed(
                resolution.winner.path, dest / basename, dry_run=args.dry_run
            )
        elif resolution.merged_content is not None:
            write_bytes_if_changed(
                resolution.merged_content, dest / basename, dry_run=args.dry_run
            )

    report = build_report(sources=sources, dest=dest, dry_run=args.dry_run, counts=counts)
    review_report = build_review_report(conflicts)

    if not args.dry_run:
        (dest / "reconcile_report.txt").write_text(report, encoding="utf-8")
        (dest / "reconcile_review.txt").write_text(review_report, encoding="utf-8")
        (dest / "reconcile_status.txt").write_text(source_git_log(sources), encoding="utf-8")

    print(report)
    if args.dry_run:
        print("Dry run: no files or reports were written.")
    else:
        print(f"Report written to: {dest / 'reconcile_report.txt'}")
        print(f"Review report written to: {dest / 'reconcile_review.txt'}")
        print(f"Status report written to: {dest / 'reconcile_status.txt'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
