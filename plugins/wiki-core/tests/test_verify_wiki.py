"""Hermetic tests for the read-only vault linter.

These build a minimal but valid ``tmp_path`` vault plus manifest, then seed one
deterministic defect per test and assert the corresponding linter section and
exit code. No real raw sources or the synced vault are touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wiki_core import verify_wiki

SOURCE_PAGE = """\
---
type: source
title: "A source about agents"
source_type: x
source_id: "111"
author: A
author_handle: a
domain: ai-swe
resource: https://x.com/a/status/111
raw: raw/x/likes/111.md
timestamp: 2026-06-29
tags: []
has_video: false
video_transcribed: false
---

# Title

> quote

body
"""

INDEX_PAGE = """\
# Index

- [src](sources/source-111.md)
- [backlog](overview.md#video-transcription-backlog)
"""

OVERVIEW_PAGE = """\
# Overview

## Video transcription backlog

Pending clips.
"""

MANIFEST = {
    "sources": {
        "111": {
            "status": "ingested",
            "wiki_page": "sources/source-111.md",
            "file": "raw/x/likes/111.md",
            "domain": "ai-swe",
            "has_video": False,
        }
    }
}


def _build_vault(tmp_path: Path) -> tuple[Path, Path]:
    """A clean vault + manifest that the linter passes with exit code 0."""
    vault = tmp_path / "wiki"
    (vault / "sources").mkdir(parents=True)
    (vault / "sources" / "source-111.md").write_text(SOURCE_PAGE, encoding="utf-8")
    (vault / "index.md").write_text(INDEX_PAGE, encoding="utf-8")
    (vault / "overview.md").write_text(OVERVIEW_PAGE, encoding="utf-8")
    manifest = tmp_path / "ingest_state.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    return vault, manifest


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    vault: Path,
    manifest: Path,
) -> tuple[int, str]:
    monkeypatch.setattr(
        sys, "argv", ["verify_wiki", "--vault", str(vault), "--manifest", str(manifest)]
    )
    code = verify_wiki.main()
    return code, capsys.readouterr().out


def test_clean_vault_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 0
    assert "broken relative links: 0" in out
    assert "broken anchor links (missing heading): 0" in out
    assert "frontmatter schema violations: 0" in out
    assert "manifest drift (ingested page missing): 0" in out
    assert "source pages not finalized as ingested: 0" in out


def test_broken_relative_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    (vault / "index.md").write_text(
        INDEX_PAGE + "\n- [gone](sources/missing.md)\n", encoding="utf-8"
    )
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "broken relative links: 1" in out
    assert "sources/missing.md" in out


def test_broken_anchor_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    (vault / "index.md").write_text(
        INDEX_PAGE + "\n- [bad](overview.md#no-such-heading)\n", encoding="utf-8"
    )
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "broken anchor links (missing heading): 1" in out
    assert "overview.md#no-such-heading" in out


def test_valid_anchor_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 0
    assert "broken anchor links (missing heading): 0" in out


def test_frontmatter_missing_key_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    page = SOURCE_PAGE.replace("resource: https://x.com/a/status/111\n", "")
    (vault / "sources" / "source-111.md").write_text(page, encoding="utf-8")
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "frontmatter schema violations: 1" in out
    assert "missing resource" in out


def test_frontmatter_wrong_type_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    concepts = vault / "concepts"
    concepts.mkdir()
    (concepts / "agent-loop.md").write_text(
        "---\ntype: entity\nname: Agent loop\ndomain: ai-swe\n---\n\n# Agent loop\n",
        encoding="utf-8",
    )
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "frontmatter schema violations: 1" in out
    assert "type 'entity' != 'concept'" in out


def test_forward_manifest_drift_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    drifted = {
        "sources": {
            "111": MANIFEST["sources"]["111"],
            "222": {
                "status": "ingested",
                "wiki_page": "sources/source-222.md",
                "file": "raw/x/likes/222.md",
                "domain": "ai-swe",
                "has_video": False,
            },
        }
    }
    manifest.write_text(json.dumps(drifted), encoding="utf-8")
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "manifest drift (ingested page missing): 1" in out
    assert "sources/source-222.md (missing on disk)" in out


def test_reverse_drift_unfinalized_is_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    parked = {
        "sources": {
            "111": {**MANIFEST["sources"]["111"], "status": "parked"},
        }
    }
    manifest.write_text(json.dumps(parked), encoding="utf-8")
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 0
    assert "source pages not finalized as ingested: 1" in out
    assert "manifest status 'parked'" in out


def test_comparison_requires_type_and_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    comparisons = vault / "comparisons"
    comparisons.mkdir()
    # A comparison page with no frontmatter violates the OKF type contract.
    (comparisons / "a-vs-b.md").write_text("# A vs B\n\nbody\n", encoding="utf-8")
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "frontmatter schema violations: 1" in out
    assert "comparisons/a-vs-b.md: missing frontmatter" in out


def test_valid_comparison_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    comparisons = vault / "comparisons"
    comparisons.mkdir()
    (comparisons / "a-vs-b.md").write_text(
        '---\ntype: comparison\ntitle: "A vs B"\ntags: []\n---\n\n'
        "# A vs B\n\n[src](../sources/source-111.md)\n",
        encoding="utf-8",
    )
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 0
    assert "frontmatter schema violations: 0" in out


def test_scalar_tags_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, manifest = _build_vault(tmp_path)
    # `tags` is optional, but if present inline it must be a YAML list.
    page = SOURCE_PAGE.replace("tags: []", "tags: agents")
    (vault / "sources" / "source-111.md").write_text(page, encoding="utf-8")
    code, out = _run(monkeypatch, capsys, vault, manifest)
    assert code == 1
    assert "tags must be a list" in out
