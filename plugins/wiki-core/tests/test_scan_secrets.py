"""Hermetic tests for the detect-secrets credential-scan wrapper.

The wrapper is exercised with explicit ``--baseline`` and file arguments so the
scan is fully contained in ``tmp_path``. The end-to-end cases reuse the
committed repository baseline (full plugin set, empty ``results``) and plant a
deterministically detected private-key block.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from wiki_core import scan_secrets

CLEAN_FILE = "# Hello\n\nNothing secret here.\n"

# PrivateKeyDetector fires on this header deterministically (no entropy or
# example-value heuristics involved).
PRIVATE_KEY_FILE = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIIBVQIBADANBgkq= not a real key payload\n"
    "-----END PRIVATE KEY-----\n"
)


def _baseline(tmp_path: Path) -> Path:
    """Copy the committed repository baseline into the test sandbox."""
    src = scan_secrets.repo_root() / ".secrets.baseline"
    dst = tmp_path / ".secrets.baseline"
    shutil.copy(src, dst)
    return dst


def test_missing_baseline_returns_2(tmp_path: Path) -> None:
    assert scan_secrets.main(["--baseline", str(tmp_path / "absent.baseline")]) == 2


def test_clean_file_passes(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path)
    clean = tmp_path / "clean.md"
    clean.write_text(CLEAN_FILE, encoding="utf-8")
    assert scan_secrets.main(["--baseline", str(baseline), str(clean)]) == 0


def test_new_secret_fails(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path)
    leaky = tmp_path / "leaky.txt"
    leaky.write_text(PRIVATE_KEY_FILE, encoding="utf-8")
    assert scan_secrets.main(["--baseline", str(baseline), str(leaky)]) == 1


def test_exit_code_and_argv_forwarded_to_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _baseline(tmp_path)
    recorded: dict[str, list[str]] = {}

    def fake_hook(argv: list[str] | None = None) -> int:
        recorded["argv"] = list(argv or [])
        return 7

    monkeypatch.setattr(scan_secrets, "hook_main", fake_hook)
    code = scan_secrets.main(["--baseline", str(baseline), "a.md", "b.md"])
    assert code == 7
    assert recorded["argv"][:2] == ["a.md", "b.md"]
    assert "--baseline" in recorded["argv"]
