from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render_record_views import (
    parse_args,
    render_records,
    resolve_input_dir,
    resolve_output_dir,
)


def test_cli_uses_input_and_output_short_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["render_record_views.py", "-i", "/input", "-o", "/output"],
    )

    args = parse_args()

    assert args.input_dir == Path("/input")
    assert args.output_dir == Path("/output")


def test_default_directories_derive_from_mermaid_environment(monkeypatch) -> None:
    monkeypatch.setenv("MERMAID", "/corpus")

    assert resolve_input_dir(None) == Path("/corpus/records")
    assert resolve_output_dir(None) == Path("/corpus/record-views")


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_merges_sorts_and_preserves_single_line_records(tmp_path: Path) -> None:
    records, views, family = tmp_path / "records", tmp_path / "views", "log_battery_records"
    write_rows(records / "serial-a" / f"{family}.serial-a.jsonl", [{"instrument_id": "A", "record_time": "2023-11-14T22:13:23.000000Z", "raw_line": "1700000003: battery A"}])
    write_rows(records / "serial-b" / f"{family}.serial-b.jsonl", [{"instrument_id": "B", "record_time": "2023-11-14T22:13:22.000000Z", "raw_line": "literal  B  "}])
    assert render_records(records, views) == {family: 2}
    assert (views / f"{family}.txt").read_text() == "2023-11-14T22:13:22.000000Z B: literal  B  \n2023-11-14T22:13:23.000000Z A: 1700000003: battery A\n"


def test_expands_grouped_lines_sorts_equal_times_deterministically(tmp_path: Path) -> None:
    records, views, family = tmp_path / "records", tmp_path / "views", "log_parameter_records"
    write_rows(records / "serial-b" / f"{family}.serial-b.jsonl", [{"instrument_id": "B", "raw_lines": ["1700000002: parameter two", "1700000001: parameter one"]}, {"instrument_id": "A", "raw_lines": ["1700000001: equal time"]}])
    render_records(records, views)
    first = (views / f"{family}.txt").read_bytes()
    render_records(records, views)
    assert (views / f"{family}.txt").read_bytes() == first
    assert first.decode() == "2023-11-14T22:13:21.000000Z A: 1700000001: equal time\n2023-11-14T22:13:21.000000Z B: 1700000001: parameter one\n2023-11-14T22:13:22.000000Z B: 1700000002: parameter two\n"


def test_preserves_duplicate_normalized_records(tmp_path: Path) -> None:
    records, views, family = tmp_path / "records", tmp_path / "views", "log_acquisition_records"
    row = {"instrument_id": "A", "record_time": "2023-11-14T22:13:20.000000Z", "raw_line": "1700000000: repeated"}
    write_rows(records / "serial-a" / f"{family}.serial-a.jsonl", [row, row])

    render_records(records, views)

    assert (views / f"{family}.txt").read_text() == "2023-11-14T22:13:20.000000Z A: 1700000000: repeated\n" * 2


def test_keeps_untimed_grouped_and_mer_source_lines_visible(tmp_path: Path) -> None:
    records, views = tmp_path / "records", tmp_path / "views"
    write_rows(records / "serial-a" / "log_testmode_records.serial-a.jsonl", [{"instrument_id": "A", "raw_lines": ["1700000000: start", "Command list"]}])
    write_rows(records / "serial-a" / "mer_parameter_records.serial-a.jsonl", [{"instrument_id": "A", "line": "<ADC GAIN=2 />"}])
    render_records(records, views)
    assert (views / "log_testmode_records.txt").read_text() == "2023-11-14T22:13:20.000000Z A: 1700000000: start\nUNTIMED A: Command list\n"
    assert (views / "mer_parameter_records.txt").read_text() == "UNTIMED A: <ADC GAIN=2 />\n"


def test_empty_family_and_rebuild_do_not_retain_stale_text(tmp_path: Path) -> None:
    records, views, family = tmp_path / "records", tmp_path / "views", "log_gps_records"
    path = records / "serial-a" / f"{family}.serial-a.jsonl"
    write_rows(path, [{"instrument_id": "A", "record_time": "2023-11-14T22:13:20.000000Z", "raw_line": "old"}])
    render_records(records, views)
    path.write_text("", encoding="utf-8")
    render_records(records, views)
    assert (views / f"{family}.txt").read_text() == ""
