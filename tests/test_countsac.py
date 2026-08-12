from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from countsac import count_sac, default_processed_dir


def write_sac(directory: Path, filename: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).touch()


def test_counts_files_dates_and_totals(tmp_path: Path) -> None:
    instrument = tmp_path / "452.020-P-0026"
    write_sac(instrument / "nested", "20230301T054423.a.MER.DET.WLT5.sac")
    write_sac(instrument, "20240102T200156.a.MER.DET.WLT5.sac")
    write_sac(instrument, "20221231T235959.a.MER.REQ.WLT5.sac")
    (tmp_path / "not-an-instrument").mkdir()

    assert count_sac(tmp_path) == [
        "                   ALL      DET      LAST_DET     REQ       LAST_REQ",
        "452.020-P-0026 :     3        2   02-Jan-2024       1    31-Dec-2022",
        "____________________________________________________________________",
        "TOTAL :              3        2                     1",
    ]


def test_exclusion_is_a_path_substring(tmp_path: Path) -> None:
    instrument = tmp_path / "452.020-P-0026"
    write_sac(instrument, "20230301T054423.a.MER.DET.WLT5.sac")
    write_sac(instrument / "IcCycle", "20240102T200156.a.MER.REQ.WLT5.sac")

    lines = count_sac(tmp_path, "IcCycle")

    assert lines[1] == "452.020-P-0026 :     1        1   01-Mar-2023       0            NaT"
    assert lines[-1] == "TOTAL :              1        1                     0"


def test_default_processed_dir_uses_mermaid_environment(monkeypatch) -> None:
    monkeypatch.setenv("MERMAID", "/corpus")

    assert default_processed_dir() == Path("/corpus/processed_everyone")
