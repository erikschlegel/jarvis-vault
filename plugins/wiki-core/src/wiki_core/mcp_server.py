#!/usr/bin/env python3
"""FastMCP server exposing the LLM Wiki hybrid retrieval engine.

Runs as its own process (outside any editor sandbox) so it can read the
iCloud Obsidian vault directly. The agent never touches the filesystem for
wiki content — it calls these five tools instead.

Tools:
    get_pulse()                  The vault's pulse.md recent-context cache.
    search_wiki(query, k)        Hybrid BM25 + dense search (RRF fused).
    read_page(path)              Full markdown of one vault page.
    expand_neighbors(path, depth) 1st-degree wikilink neighbors of a page.
    get_index()                  The vault's index.md content catalog.

Launch (stdio): python scripts/wiki_mcp_server.py
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from wiki_core import wiki_search

mcp = FastMCP("jarvis-vault")


def _load() -> wiki_search.WikiIndex:
    """Construct the loaded index, converting hard config failures into tool errors.

    ``WikiIndex()`` raises ``SystemExit`` (a ``BaseException``) when ``WIKI_VAULT``
    is unset or the index is unbuilt. Left uncaught that tears down the server
    process; convert it to a regular ``RuntimeError`` so FastMCP returns it as a
    per-call tool error and the server keeps serving other requests.
    """
    try:
        return wiki_search.WikiIndex()
    except SystemExit as exc:
        raise RuntimeError(str(exc) or "Wiki index unavailable.") from exc


@mcp.tool()
def search_wiki(query: str, k: int = 8) -> list[dict[str, Any]]:
    """Search the wiki and return the top-k matching page sections.

    Each result has: page (vault-relative path), heading, snippet, score.
    Cite the returned ``page`` paths in answers.
    """
    index = _load()
    return [
        {"page": r.page, "heading": r.heading, "snippet": r.snippet, "score": r.score}
        for r in index.search(query, k=k)
    ]


@mcp.tool()
def read_page(path: str) -> str:
    """Return the full markdown of a vault page (e.g. ``sources/foo.md``)."""
    return _load().read_page(path)


@mcp.tool()
def expand_neighbors(path: str, depth: int = 1) -> list[str]:
    """List wikilink-connected neighbor pages for graph context."""
    return _load().neighbors(path, depth=depth)


@mcp.tool()
def get_pulse() -> str:
    """Return the vault's pulse.md recent-context cache (read this first).

    The pulse is a short rolling summary of recent activity and current working
    context for session continuity. Read it before ``get_index()`` to resume
    without a recap. Degrades to a friendly message when the vault has no pulse
    yet, or when the index/vault is not configured.
    """
    try:
        return _load().read_page("pulse.md")
    except FileNotFoundError:
        return "No pulse cache yet — the vault has no pulse.md. Fall back to get_index()."
    except RuntimeError as exc:
        return f"Pulse unavailable: {exc}"


@mcp.tool()
def get_index() -> str:
    """Return the vault's index.md content catalog (read this second)."""
    try:
        return _load().read_page("index.md")
    except (FileNotFoundError, RuntimeError) as exc:
        return f"Index unavailable: {exc}"


def main() -> None:
    """Console-script entry point: run the FastMCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
