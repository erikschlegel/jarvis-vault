"""Shared fixtures for the wiki retrieval test suite.

Engine tests are hermetic: they build a throwaway index over a fixture vault in
``tmp_path`` and redirect every index-artifact path off the real
``scripts/.wiki_index/`` so a test run never touches the developer's live index
or the iCloud vault. Embeddings use the locally cached fastembed model, so no
network access is required once the model has been downloaded.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from wiki_core import wiki_search

# Fixture vault pages keyed by vault-relative path. Links are relative markdown
# links so the graph builder resolves them into 1st-degree neighbors.
_PAGES: dict[str, str] = {
    "index.md": ("# Index\n\n- [Widget](concepts/widget.md)\n- [Gadget](concepts/gadget.md)\n"),
    "concepts/widget.md": (
        "# Widget\n\n"
        "A widget is a small reusable interface component used across dashboards.\n\n"
        "Related: [Gadget](gadget.md).\n"
    ),
    "concepts/gadget.md": (
        "# Gadget\n\nA gadget is a hardware accessory. It connects to a [Widget](widget.md).\n"
    ),
    "sources/intro.md": (
        "# Intro source\n\nThis source discusses widgets and gadgets together for context.\n"
    ),
}


@pytest.fixture
def fixture_vault(tmp_path: Path) -> Path:
    """Write the interlinked fixture vault under ``tmp_path`` and return its root."""
    vault = tmp_path / "wiki"
    for rel, body in _PAGES.items():
        page = vault / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(body, encoding="utf-8")
    return vault


@pytest.fixture
def index_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every index-artifact global to a throwaway directory."""
    idx = tmp_path / ".wiki_index"
    monkeypatch.setattr(wiki_search, "INDEX_DIR", idx)
    monkeypatch.setattr(wiki_search, "PAGECACHE_DIR", idx / "pagecache")
    monkeypatch.setattr(wiki_search, "BM25_DIR", idx / "bm25")
    monkeypatch.setattr(wiki_search, "CHUNKS_PATH", idx / "chunks.json")
    monkeypatch.setattr(wiki_search, "EMBED_PATH", idx / "embeddings.npy")
    monkeypatch.setattr(wiki_search, "GRAPH_PATH", idx / "graph.json")
    monkeypatch.setattr(wiki_search, "META_PATH", idx / "meta.json")
    return idx


@pytest.fixture
def built_index(fixture_vault: Path, index_paths: Path) -> Iterator[wiki_search.WikiIndex]:
    """Build the hermetic index and yield a loaded ``WikiIndex``."""
    wiki_search.build_index(fixture_vault)
    yield wiki_search.WikiIndex()
