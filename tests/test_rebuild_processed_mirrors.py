from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rebuild_processed_mirrors import (
    REBUILD_PROCESSED_MIRRORS_VERSION,
    automaid_root,
    rebuild_processed_mirrors,
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/rebuild_processed_mirrors.py"


@pytest.fixture
def automaid_checkout(tmp_path: Path, monkeypatch) -> Path:
    """Provide a utility that records delegation without duplicating mirror logic."""
    checkout = tmp_path / "automaid checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "utils.py").write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "version = 'v-test'\n"
        "def rebuild_processed_mirrors(processed_path, mirror_base_path):\n"
        "    global output\n"
        "    output = Path(mirror_base_path)\n"
        "    output.mkdir(parents=True, exist_ok=True)\n"
        "    (output / 'called.json').write_text(json.dumps(\n"
        "        [processed_path, mirror_base_path, sys.executable]))\n"
        "def make_processed_read_only(processed_path):\n"
        "    assert (output / 'metadata/provenance.json').read_bytes() == (\n"
        "        output / 'waveforms/provenance.json').read_bytes()\n"
        "    (output / 'read-only-call.json').write_text(json.dumps(processed_path))\n"
    )
    (scripts / "main.py").write_text("raise RuntimeError('Processing must not run')\n")
    monkeypatch.setenv("AUTOMAID", str(checkout))
    monkeypatch.setenv("MERMAID", str(tmp_path / "mermaid"))
    return checkout


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
    )


def test_explicit_paths_are_forwarded_to_utils(automaid_checkout: Path, tmp_path: Path) -> None:
    processed = tmp_path / "custom processed"
    processed.mkdir()
    output = tmp_path / "custom mirrors"
    for directory in ("metadata", "waveforms"):
        (output / directory).mkdir(parents=True)
        (output / directory / "provenance.json").write_text("previous provenance\n")

    result = run_cli("-p", str(processed), "-o", str(output))

    assert result.returncode == 0, result.stderr
    assert json.loads((output / "called.json").read_text()) == [
        str(processed), str(output), sys.executable,
    ]
    assert result.stdout == f"Rebuilt processed mirrors under {output}\n"
    assert not (automaid_checkout / "scripts/__pycache__").exists()
    metadata_provenance = output / "metadata/provenance.json"
    waveform_provenance = output / "waveforms/provenance.json"
    assert metadata_provenance.read_bytes() == waveform_provenance.read_bytes()
    assert json.loads(metadata_provenance.read_text()) == {
        "automaid_version": "v-test",
        "cli_version": REBUILD_PROCESSED_MIRRORS_VERSION,
        "source_directory": str(processed),
        "source_git_commit": None,
    }
    assert json.loads((output / "read-only-call.json").read_text()) == str(processed)


@pytest.mark.parametrize("source_option", ["omitted", "default_path", "relative", "custom"])
def test_cli_preserves_source_and_output_defaults(
    automaid_checkout: Path, tmp_path: Path, monkeypatch, source_option: str,
) -> None:
    root = tmp_path / "mermaid"
    monkeypatch.chdir(tmp_path)
    processed = root / "processed"
    output = root
    args: list[str] = []
    if source_option == "default_path":
        args = ["-p", str(processed)]
    elif source_option == "relative":
        args = ["-p", "processed"]
        processed = tmp_path / "processed"
    elif source_option == "custom":
        processed = tmp_path / "custom"
        output = processed
        args = ["-p", str(processed)]
    processed.mkdir(parents=True)

    result = run_cli(*args)

    assert result.returncode == 0, result.stderr
    assert json.loads((output / "called.json").read_text())[:2] == [
        str(processed), str(output),
    ]


def test_uses_automaid_virtual_environment(
    automaid_checkout: Path, tmp_path: Path, monkeypatch,
) -> None:
    python = automaid_checkout / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    output = tmp_path / "mirrors"
    processed = tmp_path / "processed"
    processed.mkdir()
    calls = []
    run = subprocess.run

    def record_run(command, **kwargs):
        calls.append(command)
        return run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_run)

    rebuild_processed_mirrors(processed, output)

    assert next(command for command in calls if "-c" in command)[0] == str(python)


def test_shared_utility_failure_is_reported_without_success_message(
    automaid_checkout: Path, tmp_path: Path,
) -> None:
    (automaid_checkout / "scripts/utils.py").write_text(
        "version = 'v-test'\n"
        "def rebuild_processed_mirrors(processed_path, mirror_base_path):\n"
        "    raise ValueError('Duplicate mirror filename')\n"
        "def make_processed_read_only(processed_path):\n"
        "    raise AssertionError('Protection must not run after a failed rebuild')\n"
    )
    (tmp_path / "mermaid/processed").mkdir(parents=True)
    output = tmp_path / "mirrors"
    for directory in ("metadata", "waveforms"):
        (output / directory).mkdir(parents=True)
        (output / directory / "provenance.json").write_text("previous provenance\n")

    result = run_cli("-o", str(output))

    assert result.returncode == 1
    assert result.stderr.strip() == "Duplicate mirror filename"
    assert result.stdout == ""
    for directory in ("metadata", "waveforms"):
        assert (output / directory / "provenance.json").read_text() == "previous provenance\n"


def test_protection_failure_is_reported_without_success_message(
    automaid_checkout: Path, tmp_path: Path,
) -> None:
    utility = automaid_checkout / "scripts/utils.py"
    utility.write_text(
        utility.read_text()
        + "\ndef make_processed_read_only(processed_path):\n"
        "    raise PermissionError('Cannot protect processed tree')\n"
    )
    processed = tmp_path / "processed"
    processed.mkdir()
    output = tmp_path / "mirrors"

    result = run_cli("-p", str(processed), "-o", str(output))

    assert result.returncode == 1
    assert result.stderr.strip() == "Cannot protect processed tree"
    assert result.stdout == ""
    assert (output / "called.json").exists()
    assert (output / "metadata/provenance.json").is_file()
    assert (output / "waveforms/provenance.json").is_file()


def test_missing_checkout_has_actionable_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMAID", str(tmp_path / "missing"))
    (tmp_path / "processed").mkdir()

    result = run_cli("-p", str(tmp_path / "processed"), "-o", str(tmp_path / "mirrors"))

    assert result.returncode == 1
    assert "Set AUTOMAID to the automaid checkout root" in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "mirrors").exists()


def test_unset_automaid_uses_sibling_checkout(monkeypatch) -> None:
    monkeypatch.delenv("AUTOMAID", raising=False)

    assert automaid_root() == SCRIPT.parents[2] / "automaid"


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def source_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "source repository"
    processed = repository / "processed"
    processed.mkdir(parents=True)
    (processed / "source.txt").write_text("source data\n")
    git(repository, "init", "--quiet")
    git(repository, "add", "processed/source.txt")
    git(
        repository, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Initial source",
    )
    return repository


def test_clean_source_records_canonical_directory_and_full_commit(
    automaid_checkout: Path, source_repository: Path, tmp_path: Path,
) -> None:
    processed = source_repository / "processed"
    alias = tmp_path / "source alias"
    alias.symlink_to(processed, target_is_directory=True)
    output = tmp_path / "mirrors"

    result = run_cli("-p", str(alias), "-o", str(output))

    assert result.returncode == 0, result.stderr
    first_provenance = (output / "metadata/provenance.json").read_bytes()
    assert first_provenance == (output / "waveforms/provenance.json").read_bytes()
    assert json.loads(first_provenance) == {
        "automaid_version": "v-test",
        "cli_version": REBUILD_PROCESSED_MIRRORS_VERSION,
        "source_directory": str(processed),
        "source_git_commit": git(source_repository, "rev-parse", "HEAD"),
    }
    assert git(source_repository, "status", "--porcelain") == ""


@pytest.mark.parametrize("change", ["unstaged", "staged", "deleted", "untracked", "outside_source"])
def test_dirty_source_is_rejected_before_rebuild_or_provenance_changes(
    automaid_checkout: Path, source_repository: Path, tmp_path: Path, change: str,
) -> None:
    processed = source_repository / "processed"
    source = processed / "source.txt"
    if change in {"unstaged", "staged"}:
        source.write_text("changed data\n")
        if change == "staged":
            git(source_repository, "add", "processed/source.txt")
    elif change == "deleted":
        source.unlink()
    elif change == "untracked":
        directory = processed / "untracked"
        directory.mkdir()
        (directory / "data.txt").write_text("untracked data\n")
    else:
        (source_repository / "outside.txt").write_text("outside source subtree\n")
    output = tmp_path / "mirrors"
    for directory in ("metadata", "waveforms"):
        (output / directory).mkdir(parents=True)
        (output / directory / "provenance.json").write_text("previous provenance\n")

    result = run_cli("-p", str(processed), "-o", str(output))

    assert result.returncode == 1
    assert "Source repository must be clean" in result.stderr
    assert result.stdout == ""
    assert not (output / "called.json").exists()
    for directory in ("metadata", "waveforms"):
        assert (output / directory / "provenance.json").read_text() == "previous provenance\n"


def test_clean_repository_without_commit_records_null(
    automaid_checkout: Path, tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    git(processed, "init", "--quiet")
    output = tmp_path / "mirrors"

    result = run_cli("-p", str(processed), "-o", str(output))

    assert result.returncode == 0, result.stderr
    assert json.loads((output / "metadata/provenance.json").read_text())["source_git_commit"] is None


def test_untracked_submodule_files_are_rejected_even_when_configured_to_be_ignored(
    automaid_checkout: Path, source_repository: Path, tmp_path: Path,
) -> None:
    # Use a local fixture repository as the submodule source; no network access.
    git(
        source_repository, "-c", "protocol.file.allow=always", "submodule", "add",
        "--quiet", str(source_repository), "processed/submodule",
    )
    git(
        source_repository, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Add submodule",
    )
    git(source_repository, "config", "submodule.processed/submodule.ignore", "all")
    (source_repository / "processed/submodule/untracked.txt").write_text("untracked\n")
    assert git(source_repository, "status", "--porcelain") == ""
    output = tmp_path / "mirrors"

    result = run_cli("-p", str(source_repository / "processed"), "-o", str(output))

    assert result.returncode == 1
    assert "Source repository must be clean" in result.stderr
    assert not output.exists()
