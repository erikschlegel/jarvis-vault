"""Hermetic fail-soft tests for the MCP server's config-error handling.

Unlike the stdio contract test (which is an integration test needing a real
index), these run in-process and assert that an unconfigured vault or unbuilt
index surfaces as a recoverable tool error -- never a ``SystemExit`` that would
tear the server process down.
"""

from __future__ import annotations

import pytest

from wiki_core import mcp_server, wiki_search


def _raise_systemexit() -> wiki_search.WikiIndex:
    raise SystemExit("WIKI_VAULT is not set -- run: uv run wiki-init")


def test_load_converts_systemexit_to_runtimeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_search, "WikiIndex", _raise_systemexit)
    with pytest.raises(RuntimeError):
        mcp_server._load()


def test_get_pulse_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_search, "WikiIndex", _raise_systemexit)
    message = mcp_server.get_pulse()
    assert message.startswith("Pulse unavailable:")
    assert "wiki-init" in message


def test_get_index_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_search, "WikiIndex", _raise_systemexit)
    message = mcp_server.get_index()
    assert message.startswith("Index unavailable:")


def test_get_pulse_missing_file_falls_back_to_index(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoPulse:
        def read_page(self, page: str) -> str:
            raise FileNotFoundError(page)

    monkeypatch.setattr(wiki_search, "WikiIndex", lambda: _NoPulse())
    message = mcp_server.get_pulse()
    assert "get_index()" in message
