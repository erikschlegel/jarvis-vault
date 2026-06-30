"""Hermetic tests for layered ``.env`` discovery and non-raising path resolution.

These exercise the resolution order in ``wiki_core.paths`` without touching any
real ``.env`` on disk: the dotenv mapping is monkeypatched so a missing
``WIKI_VAULT`` is genuinely unconfigured regardless of the developer's
environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_core import paths


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to an empty discovered ``.env`` mapping."""
    monkeypatch.setattr(paths, "_dotenv", lambda: {})


def test_env_var_wins_over_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKI_VAULT", "/from/env")
    monkeypatch.setattr(paths, "_dotenv", lambda: {"WIKI_VAULT": "/from/dotenv"})
    assert paths.find_vault() == Path("/from/env")


def test_dotenv_used_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_VAULT", raising=False)
    monkeypatch.setattr(paths, "_dotenv", lambda: {"WIKI_VAULT": "/from/dotenv"})
    assert paths.find_vault() == Path("/from/dotenv")


def test_find_vault_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_VAULT", raising=False)
    assert paths.find_vault() is None


def test_default_vault_exits_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_VAULT", raising=False)
    with pytest.raises(SystemExit):
        paths.default_vault()


def test_index_dir_falls_back_to_cache_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_VAULT", raising=False)
    monkeypatch.delenv("WIKI_INDEX_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg-cache")
    assert paths.index_dir() == Path("/tmp/xdg-cache/jarvis-vault/index")


def test_index_dir_uses_vault_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKI_VAULT", "/vault/wiki")
    monkeypatch.delenv("WIKI_INDEX_DIR", raising=False)
    assert paths.index_dir() == Path("/vault/wiki/.wiki_index")


def test_index_dir_explicit_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKI_VAULT", "/vault/wiki")
    monkeypatch.setenv("WIKI_INDEX_DIR", "/custom/index")
    assert paths.index_dir() == Path("/custom/index")


def test_layered_discovery_prefers_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The working directory's ``.env`` sorts ahead of every higher candidate."""
    monkeypatch.chdir(tmp_path)
    candidates = paths._candidate_dotenv_paths()
    assert candidates[0] == tmp_path / ".env"
