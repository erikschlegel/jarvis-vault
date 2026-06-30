"""Hermetic tests for the required-console-script registry."""

from __future__ import annotations

import pytest

from wiki_core import console_scripts


def test_required_scripts_are_unique_and_nonempty() -> None:
    assert console_scripts.REQUIRED_SCRIPTS
    assert len(set(console_scripts.REQUIRED_SCRIPTS)) == len(console_scripts.REQUIRED_SCRIPTS)


def test_missing_scripts_empty_when_all_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        console_scripts, "installed_scripts", lambda: set(console_scripts.REQUIRED_SCRIPTS)
    )
    assert console_scripts.missing_scripts() == []


def test_missing_scripts_reports_gaps_in_declared_order(monkeypatch: pytest.MonkeyPatch) -> None:
    present = set(console_scripts.REQUIRED_SCRIPTS) - {"wiki-mcp", "x-import"}
    monkeypatch.setattr(console_scripts, "installed_scripts", lambda: present)
    assert console_scripts.missing_scripts() == ["wiki-mcp", "x-import"]
