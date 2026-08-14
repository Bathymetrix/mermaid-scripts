from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from countevt import count_evt


def write_file(directory: Path, filename: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).touch()


def sac_name(kind: str, suffix: str) -> str:
    return f"20240101T000000.{suffix}.MER.{kind}.WLT5.sac"


def evt_name(kind: str, suffix: str) -> str:
    return sac_name(kind, suffix)[:-4] + ".evt"


def table_values(lines: list[str], serial: str) -> list[int]:
    line = next(line for line in lines if line.startswith(f"{serial:>14s}  "))
    return [int(value) for value in line.replace("|", "").split()[1:]]


def test_counts_clean_categories_no_event_and_instrument_order(tmp_path: Path) -> None:
    sacdir, evtdir = tmp_path / "sac", tmp_path / "evt"
    first, second = "452.020-P-0002", "452.020-P-0010"
    write_file(sacdir / first, sac_name("REQ", "request"))
    write_file(sacdir / second, sac_name("DET", "identified"))
    write_file(sacdir / second, sac_name("DET", "unidentified"))
    write_file(sacdir / second, sac_name("REQ", "unreviewed"))
    write_file(sacdir / second, sac_name("DET", "noevent"))
    write_file(evtdir / "reviewed" / "identified", evt_name("DET", "identified"))
    write_file(evtdir / "reviewed" / "identified", evt_name("REQ", "request"))
    write_file(evtdir / "reviewed" / "unidentified", evt_name("DET", "unidentified"))
    write_file(evtdir / "unreviewed", evt_name("REQ", "unreviewed"))

    lines = count_evt(sacdir, evtdir)

    assert table_values(lines, first) == [1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert table_values(lines, second) == [2, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0]
    assert lines.index(next(line for line in lines if first in line)) < lines.index(next(line for line in lines if second in line))
    assert table_values(lines, "TOTAL") == [3, 2, 1, 1, 1, 1, 0, 1, 0, 1, 1, 1, 0]


def test_reports_event_exceptions_without_affecting_clean_counts(tmp_path: Path) -> None:
    sacdir, evtdir = tmp_path / "sac", tmp_path / "evt"
    instrument = "452.020-P-0002"
    matched = evt_name("DET", "matched")
    duplicate = evt_name("REQ", "duplicate")
    write_file(sacdir / instrument, sac_name("DET", "matched"))
    write_file(sacdir / instrument, sac_name("REQ", "duplicate"))
    write_file(evtdir / "reviewed" / "identified", matched)
    write_file(evtdir / "reviewed" / "identified" / "prelim", evt_name("DET", "prelim"))
    write_file(evtdir / "reviewed" / "other", evt_name("DET", "outside"))
    write_file(evtdir / "unreviewed", "unknown.evt")
    write_file(evtdir / "reviewed" / "identified", duplicate)
    write_file(evtdir / "unreviewed", duplicate)

    lines = count_evt(sacdir, evtdir)

    assert table_values(lines, instrument) == [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    exception_totals = {
        line.split()[0]: int(line.split()[1])
        for line in lines
        if len(line.split()) == 2 and line.split()[0] in {
            "PRELIM_EVT", "EVT_NO_SAC", "REVIEWED_UNCLASSIFIED", "DUPLICATE_EVT"
        } and line.split()[1].isdigit()
    }
    assert exception_totals == {
        "PRELIM_EVT": 1,
        "EVT_NO_SAC": 2,
        "REVIEWED_UNCLASSIFIED": 1,
        "DUPLICATE_EVT": 1,
    }
    assert "  reviewed/identified/prelim/20240101T000000.prelim.MER.DET.WLT5.evt" in lines
    assert "  reviewed/other/20240101T000000.outside.MER.DET.WLT5.evt" in lines
    duplicate_index = lines.index("DUPLICATE_EVT (1)")
    assert lines[duplicate_index + 1] == f"  {duplicate}"
    assert lines[duplicate_index + 2:duplicate_index + 4] == [
        f"    reviewed/identified/{duplicate}", f"    unreviewed/{duplicate}",
    ]
