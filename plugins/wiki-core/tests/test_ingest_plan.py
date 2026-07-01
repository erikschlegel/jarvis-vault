"""Hermetic tests for the ingest manifest-mutation helpers.

These exercise ``mark_ingested`` against a hand-built plan and an in-memory
manifest, monkeypatching ``vault_page_exists`` so no raw sources or synced vault
are touched. They lock the finalize contract the agent relies on after writing
source pages.
"""

from __future__ import annotations

from typing import Any

import pytest

from wiki_core import ingest_plan


def _record(tweet_id: str) -> dict[str, Any]:
    """Build a plan record matching ``compute_plan``'s shape for one tweet."""
    return {
        "tweet_id": tweet_id,
        "file": f"raw/x/likes/{tweet_id}.md",
        "domain": "ai-swe",
        "hash": f"hash-{tweet_id}",
        "wiki_page": f"sources/source-{tweet_id[-6:]}.md",
        "author": "someone",
        "has_video": False,
    }


def _plan(*tweet_ids: str) -> dict[str, Any]:
    """Wrap records in the bucket structure ``mark_ingested`` reads."""
    return {"buckets": {"pending": [_record(tid) for tid in tweet_ids]}}


def test_mark_ingested_finalizes_pending_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_plan, "vault_page_exists", lambda *a, **k: True)
    state: dict[str, Any] = {"sources": {"111": {"status": "pending", "hash": "stale"}}}

    written, problems = ingest_plan.mark_ingested(state, _plan("111"), ["111"], {})

    assert written == 1
    assert problems == []
    entry = state["sources"]["111"]
    assert entry["status"] == "ingested"
    assert entry["hash"] == "hash-111"
    assert entry["wiki_page"] == "sources/source-111.md"


def test_mark_ingested_skips_when_vault_page_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_plan, "vault_page_exists", lambda *a, **k: False)
    state: dict[str, Any] = {"sources": {"222": {"status": "pending", "hash": "stale"}}}

    written, problems = ingest_plan.mark_ingested(state, _plan("222"), ["222"], {})

    assert written == 0
    assert len(problems) == 1
    assert "222" in problems[0]
    assert state["sources"]["222"]["status"] == "pending"


def test_mark_ingested_allow_missing_page_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_plan, "vault_page_exists", lambda *a, **k: False)
    state: dict[str, Any] = {"sources": {}}

    written, problems = ingest_plan.mark_ingested(
        state, _plan("333"), ["333"], {}, require_page=False
    )

    assert written == 1
    assert problems == []
    assert state["sources"]["333"]["status"] == "ingested"


def test_mark_ingested_reports_unknown_tweet() -> None:
    state: dict[str, Any] = {"sources": {}}

    written, problems = ingest_plan.mark_ingested(state, _plan("444"), ["999"], {})

    assert written == 0
    assert problems == ["999: no raw source found"]
    assert state["sources"] == {}
