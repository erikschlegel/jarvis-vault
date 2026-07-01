#!/usr/bin/env python3
"""Hybrid BM25 + dense retrieval engine over the LLM Wiki vault.

Builds a derived, rebuildable index (BM25 keyword + bge-small embeddings) over
the synced Obsidian wiki and answers queries with reciprocal-rank fusion plus
1st-degree wikilink graph expansion. Local-only: embeddings run on-device via
fastembed (ONNX); no network at query time once the model is cached.

The index is throwaway state under ``<vault>/.wiki_index/`` (gitignored). A
page-level cache makes rebuilds incremental: only pages whose content hash
changed are re-embedded.

CLI:
    uv run wiki-search build [--vault PATH] [--incremental]
    uv run wiki-search query "your question" [-k 8] [--expand]
    uv run wiki-search duplicates [--threshold 0.93]
    uv run wiki-search status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from wiki_core import paths

if TYPE_CHECKING:
    from fastembed import TextEmbedding

REPO_ROOT = Path(__file__).resolve().parents[4]

# Vault root and index home resolve from WIKI_VAULT / WIKI_INDEX_DIR (see paths).
# DEFAULT_VAULT may be None when WIKI_VAULT is unset; the build CLI resolves it
# lazily so an unset vault yields setup guidance rather than an import crash.
DEFAULT_VAULT = paths.find_vault()

INDEX_DIR = paths.index_dir()
PAGECACHE_DIR = INDEX_DIR / "pagecache"
BM25_DIR = INDEX_DIR / "bm25"
CHUNKS_PATH = INDEX_DIR / "chunks.json"
EMBED_PATH = INDEX_DIR / "embeddings.npy"
GRAPH_PATH = INDEX_DIR / "graph.json"
META_PATH = INDEX_DIR / "meta.json"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
RRF_K = 60
POOL = 50  # candidates pulled from each ranker before fusion

# Inline markdown links: [text](target).
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Fenced code-block boundaries (``` or ~~~) hold template examples, not links.
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# ATX headings: one-to-six leading hashes followed by a space.
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def strip_fenced_code(text: str) -> str:
    """Drop fenced code-block lines so template examples are not linkified."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block delimited by ``---`` lines."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    newline = text.find("\n", end + 1)
    return text[newline + 1 :] if newline != -1 else ""


def is_relative_md_link(target: str) -> bool:
    """True when a link target points at a local file we can resolve on disk."""
    return not target.startswith(("http://", "https://", "mailto:", "#"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_pages(vault: Path) -> list[Path]:
    return sorted(p for p in vault.rglob("*.md"))


def page_rel(vault: Path, path: Path) -> str:
    return path.relative_to(vault).as_posix()


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split body markdown into (heading, body) sections by ATX headings.

    Content before the first heading is returned under an empty heading.
    """
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            sections.append((match.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    result: list[tuple[str, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if heading or body:
            result.append((heading, body))
    return result


@dataclass
class Chunk:
    id: int
    page: str
    heading: str
    text: str


def chunk_page(rel: str, raw: str) -> list[dict[str, str]]:
    """Produce embeddable chunks for one page (heading-section granularity)."""
    body = strip_frontmatter(raw)
    title = ""
    chunks: list[dict[str, str]] = []
    for heading, section in split_sections(body):
        if heading.startswith("# ") or (not title and heading):
            title = title or heading.lstrip("# ").strip()
        text_parts = [p for p in (heading, section) if p]
        text = "\n".join(text_parts).strip()
        if not text:
            continue
        # Prefix the page title for standalone context in retrieval.
        prefixed = f"{title}\n{text}" if title and title != heading else text
        chunks.append({"page": rel, "heading": heading, "text": prefixed})
    if not chunks:
        chunks.append({"page": rel, "heading": "", "text": rel})
    return chunks


def build_graph(vault: Path, pages: list[Path]) -> dict[str, list[str]]:
    """Undirected 1st-degree wikilink adjacency keyed by vault-relative path."""
    adjacency: dict[str, set[str]] = {page_rel(vault, p): set() for p in pages}
    for src in pages:
        src_rel = page_rel(vault, src)
        text = strip_fenced_code(src.read_text(encoding="utf-8", errors="replace"))
        for raw_target in LINK_RE.findall(text):
            target = raw_target.split("#", 1)[0].strip()
            if not target or not is_relative_md_link(target):
                continue
            resolved = (src.parent / target).resolve()
            if resolved.suffix != ".md" or not resolved.exists():
                continue
            try:
                dst_rel = resolved.relative_to(vault).as_posix()
            except ValueError:
                continue
            if dst_rel == src_rel:
                continue
            adjacency[src_rel].add(dst_rel)
            adjacency.setdefault(dst_rel, set()).add(src_rel)
    return {k: sorted(v) for k, v in adjacency.items()}


# --------------------------------------------------------------------------- #
# Embeddings (lazy: fastembed model loads only when needed)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _embedder() -> TextEmbedding:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBED_MODEL)


def embed_texts(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    vectors = np.array(list(_embedder().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


# --------------------------------------------------------------------------- #
# Index build (page-level incremental cache)
# --------------------------------------------------------------------------- #
def _cache_path(rel: str) -> Path:
    return PAGECACHE_DIR / f"{hashlib.sha1(rel.encode()).hexdigest()}.json"


def build_index(vault: Path, incremental: bool = False) -> dict[str, Any]:
    import bm25s

    if not vault.is_dir():
        raise SystemExit(f"ERROR: vault wiki root not found: {vault}")

    PAGECACHE_DIR.mkdir(parents=True, exist_ok=True)
    pages = iter_pages(vault)
    rel_paths = {page_rel(vault, p) for p in pages}

    prior_meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    model_changed = prior_meta.get("embed_model") != EMBED_MODEL

    if incremental and not model_changed and META_PATH.exists():
        current = {
            page_rel(vault, p): sha256_text(p.read_text(encoding="utf-8", errors="replace"))
            for p in pages
        }
        if current == prior_meta.get("page_hashes") and rel_paths == set(
            prior_meta.get("page_hashes", {})
        ):
            return {
                "status": "up-to-date",
                "pages": len(pages),
                "chunks": prior_meta.get("n_chunks", 0),
                "embedded": 0,
                "reused": len(pages),
            }

    chunks: list[Chunk] = []
    vectors: list[np.ndarray] = []
    page_hashes: dict[str, str] = {}
    embedded_pages = 0
    reused_pages = 0
    next_id = 0

    for path in pages:
        rel = page_rel(vault, path)
        raw = path.read_text(encoding="utf-8", errors="replace")
        page_hash = sha256_text(raw)
        page_hashes[rel] = page_hash
        cache_file = _cache_path(rel)

        cached = None
        if not model_changed and cache_file.exists():
            try:
                candidate = json.loads(cache_file.read_text())
                if candidate.get("hash") == page_hash and candidate.get("model") == EMBED_MODEL:
                    cached = candidate
            except json.JSONDecodeError:
                cached = None

        if cached is not None:
            page_chunks = cached["chunks"]
            page_vecs = np.array(cached["emb"], dtype=np.float32)
            reused_pages += 1
        else:
            page_chunks = chunk_page(rel, raw)
            page_vecs = embed_texts([c["text"] for c in page_chunks])
            cache_file.write_text(
                json.dumps(
                    {
                        "page": rel,
                        "hash": page_hash,
                        "model": EMBED_MODEL,
                        "chunks": page_chunks,
                        "emb": page_vecs.tolist(),
                    }
                )
            )
            embedded_pages += 1

        for c, v in zip(page_chunks, page_vecs, strict=True):
            chunks.append(Chunk(id=next_id, page=c["page"], heading=c["heading"], text=c["text"]))
            vectors.append(v)
            next_id += 1

    # Prune cache files for pages that no longer exist.
    live_caches = {_cache_path(r).name for r in rel_paths}
    for stale in PAGECACHE_DIR.glob("*.json"):
        if stale.name not in live_caches:
            stale.unlink()

    embeddings = (
        np.array(vectors, dtype=np.float32)
        if vectors
        else np.zeros((0, EMBED_DIM), dtype=np.float32)
    )

    # BM25 is cheap to rebuild fully from the current chunk set.
    corpus_tokens = bm25s.tokenize([c.text for c in chunks], stopwords="en", show_progress=False)
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)
    if BM25_DIR.exists():
        import shutil

        shutil.rmtree(BM25_DIR)
    retriever.save(str(BM25_DIR))

    np.save(EMBED_PATH, embeddings)
    CHUNKS_PATH.write_text(json.dumps([asdict(c) for c in chunks]))
    GRAPH_PATH.write_text(json.dumps(build_graph(vault, pages)))
    META_PATH.write_text(
        json.dumps(
            {
                "embed_model": EMBED_MODEL,
                "embed_dim": EMBED_DIM,
                "n_chunks": len(chunks),
                "n_pages": len(pages),
                "vault": str(vault),
                "built_at": datetime.now(UTC).isoformat(),
                "page_hashes": page_hashes,
            },
            indent=2,
        )
    )
    return {
        "status": "rebuilt",
        "pages": len(pages),
        "chunks": len(chunks),
        "embedded": embedded_pages,
        "reused": reused_pages,
    }


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
@dataclass
class SearchResult:
    page: str
    heading: str
    snippet: str
    score: float


def page_vectors(
    chunks: list[dict[str, Any]], embeddings: np.ndarray
) -> tuple[list[str], np.ndarray]:
    """Aggregate chunk embeddings into one normalized vector per page."""
    by_page: dict[str, list[int]] = {}
    for c in chunks:
        by_page.setdefault(c["page"], []).append(int(c["id"]))
    pages = sorted(by_page)
    dim = embeddings.shape[1] if embeddings.ndim == 2 and embeddings.shape[0] else EMBED_DIM
    matrix = np.zeros((len(pages), dim), dtype=np.float32)
    if embeddings.shape[0] == 0:
        return pages, matrix
    for row, page in enumerate(pages):
        mean = embeddings[by_page[page]].mean(axis=0)
        norm = float(np.linalg.norm(mean))
        matrix[row] = mean / norm if norm else mean
    return pages, matrix


def find_duplicate_pairs(
    pages: list[str], matrix: np.ndarray, threshold: float
) -> list[tuple[str, str, float]]:
    """Page pairs whose cosine similarity meets or exceeds ``threshold``."""
    if len(pages) < 2:
        return []
    sims = matrix @ matrix.T
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            score = float(sims[i, j])
            if score >= threshold:
                pairs.append((pages[i], pages[j], round(score, 4)))
    pairs.sort(key=lambda t: t[2], reverse=True)
    return pairs


class WikiIndex:
    """Loaded hybrid index ready to answer queries."""

    def __init__(self) -> None:
        if not META_PATH.exists():
            if paths.find_vault() is None:
                raise SystemExit(
                    "WIKI_VAULT is not set -- point it at your Obsidian vault wiki root "
                    "(the folder holding index.md), then run: uv run wiki-init"
                )
            raise SystemExit(
                "Index not built. Run: uv run wiki-init  (or: uv run wiki-search build)"
            )
        import bm25s

        self.meta = json.loads(META_PATH.read_text())
        self.chunks = json.loads(CHUNKS_PATH.read_text())
        self.embeddings = np.load(EMBED_PATH)
        self.graph = json.loads(GRAPH_PATH.read_text())
        self.bm25 = bm25s.BM25.load(str(BM25_DIR), load_corpus=False)
        self.vault = Path(self.meta["vault"])

    def _dense_ranking(self, query: str, pool: int) -> list[int]:
        if self.embeddings.shape[0] == 0:
            return []
        qvec = embed_texts([query])[0]
        scores = self.embeddings @ qvec
        top = np.argsort(scores)[::-1][:pool]
        return [int(i) for i in top]

    def _sparse_ranking(self, query: str, pool: int) -> list[int]:
        import bm25s

        tokens = bm25s.tokenize(query, stopwords="en", show_progress=False)
        k = min(pool, len(self.chunks))
        if k == 0:
            return []
        results, _ = self.bm25.retrieve(tokens, k=k, show_progress=False)
        return [int(i) for i in results[0]]

    def search(self, query: str, k: int = 8) -> list[SearchResult]:
        dense = self._dense_ranking(query, POOL)
        sparse = self._sparse_ranking(query, POOL)
        fused: dict[int, float] = {}
        for ranking in (dense, sparse):
            for rank, chunk_id in enumerate(ranking):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        out: list[SearchResult] = []
        for chunk_id, score in ordered:
            c = self.chunks[chunk_id]
            snippet = " ".join(c["text"].split())[:280]
            out.append(
                SearchResult(
                    page=c["page"], heading=c["heading"], snippet=snippet, score=round(score, 5)
                )
            )
        return out

    def neighbors(self, page: str, depth: int = 1) -> list[str]:
        seen = {page}
        frontier = {page}
        for _ in range(max(1, depth)):
            nxt: set[str] = set()
            for node in frontier:
                for neighbor in self.graph.get(node, []):
                    if neighbor not in seen:
                        nxt.add(neighbor)
            seen |= nxt
            frontier = nxt
        return sorted(seen - {page})

    def duplicate_pairs(self, threshold: float) -> list[tuple[str, str, float]]:
        pages, matrix = page_vectors(self.chunks, self.embeddings)
        return find_duplicate_pairs(pages, matrix, threshold)

    def read_page(self, page: str) -> str:
        target = (self.vault / page).resolve()
        if not str(target).startswith(str(self.vault.resolve())):
            raise ValueError("path escapes vault root")
        if not target.exists():
            raise FileNotFoundError(page)
        return target.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build or refresh the index.")
    p_build.add_argument("--vault", type=Path, default=None)
    p_build.add_argument(
        "--incremental", action="store_true", help="Skip rebuild when no page changed."
    )

    p_query = sub.add_parser("query", help="Run a hybrid search.")
    p_query.add_argument("text")
    p_query.add_argument("-k", type=int, default=8)
    p_query.add_argument(
        "--expand", action="store_true", help="Also list 1st-degree neighbor pages."
    )

    p_dupes = sub.add_parser(
        "duplicates", help="Report near-duplicate page pairs by cosine similarity."
    )
    p_dupes.add_argument(
        "--threshold", type=float, default=0.93, help="Minimum cosine similarity to report."
    )

    sub.add_parser("status", help="Show index metadata.")

    args = parser.parse_args()

    if args.command == "build":
        vault = args.vault or paths.default_vault()
        report = build_index(vault, incremental=args.incremental)
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "status":
        if not META_PATH.exists():
            print("Index not built.")
            return 1
        print(META_PATH.read_text())
        return 0

    if args.command == "query":
        index = WikiIndex()
        results = index.search(args.text, k=args.k)
        for i, r in enumerate(results, 1):
            head = f" › {r.heading}" if r.heading else ""
            print(f"{i}. [{r.score}] {r.page}{head}")
            print(f"   {r.snippet}")
        if args.expand and results:
            pages = list(dict.fromkeys(r.page for r in results))
            extra = sorted({n for p in pages for n in index.neighbors(p)} - set(pages))
            print("\nNeighbors:")
            for n in extra[:20]:
                print(f"  - {n}")
        return 0

    if args.command == "duplicates":
        index = WikiIndex()
        pairs = index.duplicate_pairs(args.threshold)
        print(f"near-duplicate page pairs (cosine >= {args.threshold}): {len(pairs)}")
        for first, second, score in pairs:
            print(f"  [{score}] {first}  <->  {second}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
