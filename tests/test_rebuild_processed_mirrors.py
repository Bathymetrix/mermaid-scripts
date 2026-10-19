from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rebuild_processed_mirrors import MIRROR_DIRECTORIES, rebuild_processed_mirrors


def write_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("source data\n")
    return path


def test_rebuilds_waveforms_and_prefixed_metadata(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    instrument = processed / "452.020-P-06"
    files = {
        "waveforms/sac/record.sac": instrument / "cycle" / "record.sac",
        "waveforms/mseed/record.mseed": instrument / "cycle" / "record.mseed",
        "metadata/geocsv/452.020-P-06-geo_DET_REQ.csv": instrument / "geo_DET_REQ.csv",
        "metadata/gps/452.020-P-06-gps.txt": instrument / "gps.txt",
        "metadata/gps/452.020-P-06-gps.csv": instrument / "gps.csv",
        "metadata/gps/452.120-S-0081-gps.csv": processed / "452.120-S-0081" / "gps.csv",
    }
    for source in files.values():
        write_file(source)
    write_file(instrument / "gps_interpolation.txt")
    write_file(instrument / "geo_REQ-CLASHES.md")
    write_file(instrument / "upper.SAC")
    stale = tmp_path / "metadata/gps/stale.txt"
    stale.parent.mkdir(parents=True)
    stale.symlink_to(tmp_path / "missing")
    git_file = write_file(tmp_path / "waveforms/.git/keep")

    counts = rebuild_processed_mirrors(processed, tmp_path)

    assert counts == {
        "waveforms/sac": 1, "waveforms/mseed": 1,
        "metadata/geocsv": 1, "metadata/gps": 3,
    }
    assert not stale.is_symlink()
    assert git_file.read_text() == "source data\n"
    for name, source in files.items():
        link = tmp_path / name
        assert link.is_symlink()
        assert link.readlink() == source
        assert link.read_text() == "source data\n"

    # A subsequent rebuild must remove links whose sources disappeared.
    (instrument / "gps.txt").unlink()
    assert rebuild_processed_mirrors(processed, tmp_path)["metadata/gps"] == 2
    assert not (tmp_path / "metadata/gps/452.020-P-06-gps.txt").is_symlink()


@pytest.mark.parametrize("filename", ["same.sac", "same.mseed", "geo_DET.csv", "gps.csv"])
def test_collisions_leave_existing_mirrors_intact(tmp_path: Path, filename: str) -> None:
    processed = tmp_path / "processed"
    instrument = processed / "452.020-P-06"
    write_file(instrument / "one" / filename)
    write_file(instrument / "two" / filename)
    stale = tmp_path / "waveforms/sac/stale.sac"
    stale.parent.mkdir(parents=True)
    stale.symlink_to(tmp_path / "missing")

    with pytest.raises(ValueError, match="Multiple files share"):
        rebuild_processed_mirrors(processed, tmp_path)

    assert stale.is_symlink()


def test_nested_outputs_are_not_rediscovered(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    write_file(processed / "452.020-P-06/cycle/record.sac")
    write_file(processed / "452.020-P-06/gps.csv")

    first_counts = rebuild_processed_mirrors(processed, processed)

    assert rebuild_processed_mirrors(processed, processed) == first_counts
    assert first_counts["metadata/gps"] == 1
    assert first_counts["waveforms/sac"] == 1


def test_non_symlink_data_is_preserved_before_any_rebuild(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    write_file(processed / "452.020-P-06/record.sac")
    stale = tmp_path / "waveforms/sac/stale.sac"
    stale.parent.mkdir(parents=True)
    stale.symlink_to(tmp_path / "missing")
    data = write_file(tmp_path / "metadata/gps/keep.txt")

    with pytest.raises(ValueError, match="Refusing to remove non-symlink"):
        rebuild_processed_mirrors(processed, tmp_path)

    assert stale.is_symlink()
    assert data.read_text() == "source data\n"


def test_missing_source_does_not_clear_existing_mirror(tmp_path: Path) -> None:
    stale = tmp_path / "waveforms/sac/stale.sac"
    stale.parent.mkdir(parents=True)
    stale.symlink_to(tmp_path / "missing")

    with pytest.raises(ValueError, match="Processed directory does not exist"):
        rebuild_processed_mirrors(tmp_path / "missing", tmp_path)

    assert stale.is_symlink()


def test_empty_archive_creates_all_mirrors(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()

    assert rebuild_processed_mirrors(processed, tmp_path) == {
        name: 0 for name in MIRROR_DIRECTORIES
    }
    assert all((tmp_path / name).is_dir() for name in MIRROR_DIRECTORIES)
