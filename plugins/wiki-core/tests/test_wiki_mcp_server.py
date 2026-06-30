"""MCP stdio contract test for the wiki server.

Spawns ``wiki_core.mcp_server`` over stdio and asserts the tool surface and the
``search_wiki`` result shape. This is an integration test that depends on the
real index being built (``wiki-search build``); it is skipped
otherwise and marked ``integration`` so it can be deselected offline.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest

from wiki_core import wiki_search

pytestmark = pytest.mark.integration

_EXPECTED_TOOLS = ["expand_neighbors", "get_index", "get_pulse", "read_page", "search_wiki"]

requires_index = pytest.mark.skipif(
    not wiki_search.META_PATH.exists(),
    reason="real wiki index not built; run `wiki-search build`",
)


def _unwrap_list(result: Any) -> Any:
    """Unwrap a list-returning tool result.

    FastMCP wraps list returns as ``{"result": [...]}`` in ``structuredContent``;
    fall back to parsing the first text content block as JSON.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    return json.loads(result.content[0].text)


async def _run_contract() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "wiki_core.mcp_server"],
        cwd=str(wiki_search.REPO_ROOT),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        listed = await session.list_tools()
        assert sorted(t.name for t in listed.tools) == _EXPECTED_TOOLS

        result = await session.call_tool("search_wiki", {"query": "agent memory", "k": 3})
        hits = _unwrap_list(result)
        assert isinstance(hits, list)
        assert hits, "search_wiki returned no hits"
        assert {"page", "heading", "snippet", "score"} <= set(hits[0])


@requires_index
def test_mcp_stdio_contract() -> None:
    asyncio.run(_run_contract())
