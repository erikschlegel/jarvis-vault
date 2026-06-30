"""Hermetic unit tests for the wiki retrieval engine.

Parsing helpers are pure and need no index. Index-level tests build a throwaway
index over the fixture vault (see ``conftest.py``) and assert ranking sanity,
graph expansion, safe page reads, and build determinism without touching the
real index or the iCloud vault.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from wiki_core import wiki_search

# --------------------------------------------------------------------------- #
# Pure parsing helpers
# --------------------------------------------------------------------------- #


def test_strip_frontmatter_removes_leading_block() -> None:
    text = "---\ntitle: Demo\ntags: [a]\n---\nbody text\n"
    stripped = wiki_search.strip_frontmatter(text)
    assert stripped.strip() == "body text"
    assert "title: Demo" not in stripped


def test_strip_frontmatter_passthrough_without_block() -> None:
    text = "no frontmatter here\n"
    assert wiki_search.strip_frontmatter(text) == text


def test_strip_fenced_code_drops_code_lines() -> None:
    text = "before\n```python\nlink = '[x](y.md)'\n```\nafter"
    stripped = wiki_search.strip_fenced_code(text)
    assert "before" in stripped
    assert "after" in stripped
    assert "y.md" not in stripped


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("notes.md", True),
        ("concepts/widget.md", True),
        ("https://example.com", False),
        ("http://example.com", False),
        ("mailto:a@b.com", False),
        ("#heading", False),
    ],
)
def test_is_relative_md_link(target: str, expected: bool) -> None:
    assert wiki_search.is_relative_md_link(target) is expected


def test_sha256_text_is_stable_and_distinct() -> None:
    assert wiki_search.sha256_text("abc") == wiki_search.sha256_text("abc")
    assert wiki_search.sha256_text("abc") != wiki_search.sha256_text("abd")


def test_split_sections_keys_on_headings() -> None:
    headings = [h for h, _ in wiki_search.split_sections("# Title\nintro\n## Sub\nbody")]
    assert "Title" in headings
    assert "Sub" in headings


def test_chunk_page_emits_page_scoped_chunks() -> None:
    chunks = wiki_search.chunk_page("concepts/widget.md", "# Widget\nA reusable component.")
    assert chunks
    assert all(c["page"] == "concepts/widget.md" for c in chunks)
    assert any("reusable component" in c["text"] for c in chunks)


# --------------------------------------------------------------------------- #
# Near-duplicate detection (pure)
# --------------------------------------------------------------------------- #


def test_page_vectors_aggregates_and_normalizes_per_page() -> None:
    chunks = [
        {"id": 0, "page": "a.md"},
        {"id": 1, "page": "a.md"},
        {"id": 2, "page": "b.md"},
    ]
    embeddings = np.array([[3.0, 0.0], [3.0, 0.0], [0.0, 5.0]], dtype=np.float32)
    pages, matrix = wiki_search.page_vectors(chunks, embeddings)
    assert pages == ["a.md", "b.md"]
    assert matrix.shape == (2, 2)
    np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), [1.0, 1.0], atol=1e-6)
    np.testing.assert_allclose(matrix[0], [1.0, 0.0], atol=1e-6)


def test_page_vectors_handles_empty_embeddings() -> None:
    pages, matrix = wiki_search.page_vectors([], np.zeros((0, 4), dtype=np.float32))
    assert pages == []
    assert matrix.shape[0] == 0


def test_find_duplicate_pairs_flags_and_sorts_by_similarity() -> None:
    pages = ["a.md", "b.md", "c.md"]
    matrix = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    pairs = wiki_search.find_duplicate_pairs(pages, matrix, threshold=0.9)
    assert pairs == [("a.md", "b.md", 1.0)]


def test_find_duplicate_pairs_requires_two_pages() -> None:
    matrix = np.array([[1.0, 0.0]], dtype=np.float32)
    assert wiki_search.find_duplicate_pairs(["a.md"], matrix, threshold=0.0) == []


# --------------------------------------------------------------------------- #
# Index build and retrieval (hermetic)
# --------------------------------------------------------------------------- #


def test_build_reports_pages_and_chunks(fixture_vault: Path, index_paths: Path) -> None:
    report = wiki_search.build_index(fixture_vault)
    assert report["status"] == "rebuilt"
    assert report["pages"] == 4
    assert report["chunks"] >= 4
    assert (index_paths / "meta.json").exists()


def test_search_ranks_expected_page_first(built_index: wiki_search.WikiIndex) -> None:
    results = built_index.search("widget reusable interface component", k=3)
    assert results
    assert results[0].page == "concepts/widget.md"
    for r in results:
        assert isinstance(r, wiki_search.SearchResult)
        assert r.score > 0
        assert r.snippet


def test_neighbors_resolves_first_degree_wikilinks(
    built_index: wiki_search.WikiIndex,
) -> None:
    neighbors = built_index.neighbors("concepts/widget.md")
    assert "concepts/gadget.md" in neighbors
    assert "index.md" in neighbors


def test_read_page_roundtrips_and_guards_paths(
    built_index: wiki_search.WikiIndex,
) -> None:
    content = built_index.read_page("concepts/widget.md")
    assert "reusable interface component" in content
    with pytest.raises(FileNotFoundError):
        built_index.read_page("concepts/missing.md")
    with pytest.raises(ValueError, match="escapes vault"):
        built_index.read_page("../../../etc/passwd")


def test_build_is_deterministic_and_incremental(fixture_vault: Path, index_paths: Path) -> None:
    wiki_search.build_index(fixture_vault)
    first_meta = json.loads((index_paths / "meta.json").read_text())

    second = wiki_search.build_index(fixture_vault, incremental=True)
    assert second["status"] == "up-to-date"

    wiki_search.build_index(fixture_vault)
    third_meta = json.loads((index_paths / "meta.json").read_text())
    assert first_meta["page_hashes"] == third_meta["page_hashes"]


def test_duplicate_pairs_method_returns_sorted_list(
    built_index: wiki_search.WikiIndex,
) -> None:
    pairs = built_index.duplicate_pairs(threshold=0.0)
    assert isinstance(pairs, list)
    scores = [score for _, _, score in pairs]
    assert scores == sorted(scores, reverse=True)
    assert built_index.duplicate_pairs(threshold=1.1) == []
