from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rebuild_processed_mirrors import automaid_root, rebuild_processed_mirrors


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
        "def rebuild_processed_mirrors(processed_path, mirror_base_path):\n"
        "    output = Path(mirror_base_path)\n"
        "    output.mkdir(parents=True, exist_ok=True)\n"
        "    (output / 'called.json').write_text(json.dumps(\n"
        "        [processed_path, mirror_base_path, sys.executable]))\n"
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
    output = tmp_path / "custom mirrors"

    result = run_cli("-p", str(processed), "-o", str(output))

    assert result.returncode == 0, result.stderr
    assert json.loads((output / "called.json").read_text()) == [
        str(processed), str(output), sys.executable,
    ]
    assert result.stdout == f"Rebuilt processed mirrors under {output}\n"
    assert not (automaid_checkout / "scripts/__pycache__").exists()


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
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: calls.append(command))

    rebuild_processed_mirrors(tmp_path / "processed", output)

    assert calls[0][0] == str(python)


def test_shared_utility_failure_is_reported_without_success_message(
    automaid_checkout: Path, tmp_path: Path,
) -> None:
    (automaid_checkout / "scripts/utils.py").write_text(
        "def rebuild_processed_mirrors(processed_path, mirror_base_path):\n"
        "    raise ValueError('Duplicate mirror filename')\n"
    )

    result = run_cli("-o", str(tmp_path / "mirrors"))

    assert result.returncode == 1
    assert result.stderr.strip() == "Duplicate mirror filename"
    assert result.stdout == ""


def test_missing_checkout_has_actionable_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMAID", str(tmp_path / "missing"))

    result = run_cli("-p", str(tmp_path / "processed"), "-o", str(tmp_path / "mirrors"))

    assert result.returncode == 1
    assert "Set AUTOMAID to the automaid checkout root" in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "mirrors").exists()


def test_unset_automaid_uses_sibling_checkout(monkeypatch) -> None:
    monkeypatch.delenv("AUTOMAID", raising=False)

    assert automaid_root() == SCRIPT.parents[2] / "automaid"
