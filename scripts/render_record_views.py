#!/usr/bin/env python3
"""Render disposable, grep-friendly views of normalized MERMAID JSONL records."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

UNTIMED_MARKER = "UNTIMED"
_RAW_TIMESTAMP = re.compile(r"^(?P<time>.+?):")


@dataclass(frozen=True)
class RenderedLine:
    time: str | None
    instrument_id: str
    raw_line: str
    source_path: Path
    record_index: int
    raw_line_index: int

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.time is None,
            self.time or "",
            self.instrument_id,
            self.source_path.as_posix(),
            self.record_index,
            self.raw_line_index,
        )

    def render(self) -> str:
        return f"{self.time or UNTIMED_MARKER} {self.instrument_id}: {self.raw_line}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build flat views from mermaid-records JSONL."
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        help="Normalized records directory. Defaults to $MERMAID/records.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Rendered view directory. Defaults to $MERMAID/record-views.",
    )
    return parser.parse_args()


def resolve_mermaid_root() -> Path:
    mermaid_root = os.environ.get("MERMAID")
    if mermaid_root:
        return Path(mermaid_root).expanduser()
    raise SystemExit(
        "MERMAID is not set. Provide --input-dir and --output-dir, or set MERMAID."
    )


def resolve_input_dir(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser()
    return resolve_mermaid_root() / "records"


def resolve_output_dir(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser()
    return resolve_mermaid_root() / "record-views"


def discover_family_files(records_dir: Path) -> dict[str, list[Path]]:
    families: dict[str, list[Path]] = {}
    for instrument_dir in sorted(path for path in records_dir.iterdir() if path.is_dir()):
        suffix = f".{instrument_dir.name}.jsonl"
        for path in sorted(instrument_dir.glob(f"*{suffix}")):
            family = path.name.removesuffix(suffix)
            if family:
                families.setdefault(family, []).append(path)
    return families


def render_records(
    records_dir: Path,
    output_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    if not records_dir.is_dir():
        raise ValueError(f"Records directory does not exist or is not a directory: {records_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for family, paths in discover_family_files(records_dir).items():
        if progress is not None:
            progress(f"Rendering {family} from {len(paths)} JSONL file(s)...")
        lines = [line for path in paths for line in iter_rendered_lines(path)]
        lines.sort(key=RenderedLine.sort_key)
        content = "\n".join(line.render() for line in lines)
        atomic_write(output_dir / f"{family}.txt", content + ("\n" if lines else ""))
        counts[family] = len(lines)
        if progress is not None:
            progress(f"Wrote {family}.txt ({len(lines)} rendered line(s)).")
    return counts


def iter_rendered_lines(path: Path) -> list[RenderedLine]:
    rendered: list[RenderedLine] = []
    with path.open(encoding="utf-8") as handle:
        for record_index, text in enumerate(handle):
            if not text.strip():
                continue
            row = json.loads(text)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{record_index + 1} is not a JSON object")
            instrument_id = required_string(row, "instrument_id", path, record_index)
            if isinstance(row.get("raw_line"), str):
                line_text = row.get("message", row["raw_line"])
                if not isinstance(line_text, str):
                    raise ValueError(f"{path}:{record_index + 1} message is not a string")
                rendered.append(
                    make_line(
                        row.get("record_time"),
                        instrument_id,
                        line_text,
                        path,
                        record_index,
                        0,
                    )
                )
            elif isinstance(row.get("raw_lines"), list):
                rendered.extend(
                    grouped_rendered_lines(
                        row,
                        instrument_id=instrument_id,
                        path=path,
                        record_index=record_index,
                    )
                )
            elif isinstance(row.get("line"), str):
                rendered.append(
                    make_line(
                        row.get("gpsinfo_date"),
                        instrument_id,
                        row["line"],
                        path,
                        record_index,
                        0,
                    )
                )
            elif "raw_info_line" in row or "raw_format_line" in row:
                for raw_line_index, field in enumerate(("raw_info_line", "raw_format_line")):
                    raw_line = row.get(field)
                    if raw_line is not None:
                        if not isinstance(raw_line, str):
                            raise ValueError(f"{path}:{record_index + 1} {field} is not a string")
                        time = (
                            row.get("event_info_date")
                            if field == "raw_info_line"
                            else None
                        )
                        rendered.append(
                            make_line(
                                time,
                                instrument_id,
                                raw_line,
                                path,
                                record_index,
                                raw_line_index,
                            )
                        )
            else:
                raise ValueError(f"{path}:{record_index + 1} has no preserved raw text representation")
    return rendered


def grouped_rendered_lines(
    row: dict[str, object],
    *,
    instrument_id: str,
    path: Path,
    record_index: int,
) -> list[RenderedLine]:
    """Render grouped source lines, using Iridium's nested parsed messages."""
    raw_lines = row["raw_lines"]
    if not isinstance(raw_lines, list):
        raise AssertionError("raw_lines was checked by iter_rendered_lines")
    source_line_numbers = row.get("source_line_numbers")
    iridium_events = row.get("iridium_events")
    events_by_line_number: dict[int, dict[str, object]] = {}
    if isinstance(source_line_numbers, list) and isinstance(iridium_events, list):
        for event in iridium_events:
            if not isinstance(event, dict):
                raise ValueError(f"{path}:{record_index + 1} iridium_events contains a non-object")
            line_number = event.get("source_line_number")
            message = event.get("message")
            if isinstance(line_number, int) and isinstance(message, str):
                events_by_line_number[line_number] = event

    lines: list[RenderedLine] = []
    for raw_line_index, raw_line in enumerate(raw_lines):
        if not isinstance(raw_line, str):
            raise ValueError(f"{path}:{record_index + 1} raw_lines contains a non-string")
        source_line_number = (
            source_line_numbers[raw_line_index]
            if isinstance(source_line_numbers, list)
            and raw_line_index < len(source_line_numbers)
            else None
        )
        event = events_by_line_number.get(source_line_number)
        time = event.get("record_time") if event is not None else time_from_raw_line(raw_line)
        line_text = event["message"] if event is not None else raw_line
        lines.append(
            make_line(
                time,
                instrument_id,
                line_text,
                path,
                record_index,
                raw_line_index,
            )
        )
    return lines


def required_string(row: dict[str, object], field: str, path: Path, record_index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{path}:{record_index + 1} is missing string {field!r}")
    return value


def make_line(
    time: object,
    instrument_id: str,
    raw_line: str,
    path: Path,
    record_index: int,
    raw_line_index: int,
) -> RenderedLine:
    if time is not None and not isinstance(time, str):
        raise ValueError(f"{path}:{record_index + 1} has a non-string timestamp")
    return RenderedLine(time, instrument_id, raw_line, path, record_index, raw_line_index)


def time_from_raw_line(raw_line: str) -> str | None:
    match = _RAW_TIMESTAMP.match(raw_line)
    if match is None:
        return None
    source_time = match.group("time")
    try:
        if source_time.isdigit():
            value = datetime.fromtimestamp(int(source_time), tz=timezone.utc)
        else:
            value = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
            value = (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
    except ValueError:
        return None
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(content)
    temporary_path.replace(path)


def main() -> int:
    args = parse_args()
    input_dir = resolve_input_dir(args.input_dir)
    output_dir = resolve_output_dir(args.output_dir)
    print(f"Reading normalized JSONL from {input_dir}", flush=True)
    print(f"Rebuilding record views in {output_dir}", flush=True)
    counts = render_records(
        input_dir,
        output_dir,
        progress=lambda message: print(message, flush=True),
    )
    print(f"Completed {len(counts)} record family view(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
