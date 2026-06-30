"""Hermetic tests for the deterministic wiki authoring + roll-up helpers.

These exercise the pure builders and the file-mutating helpers against a
``tmp_path`` vault, pointing ``WIKI_RAW`` at a tmp raw tree so no real raw
sources or the iCloud vault are touched. They lock the scaffold idempotency
contract and the index/log roll-up shapes the agent relies on.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from wiki_core import ingest_plan, wiki_pages


def _record(tweet_id: str, **overrides: Any) -> dict[str, Any]:
    """A plan record matching ``compute_plan``'s shape for one tweet."""
    record: dict[str, Any] = {
        "tweet_id": tweet_id,
        "file": f"raw/x/likes/{tweet_id}.md",
        "domain": "ai-swe",
        "hash": f"hash-{tweet_id}",
        "wiki_page": f"sources/source-{tweet_id[-6:]}.md",
        "author": "Some One",
        "has_video": False,
    }
    record.update(overrides)
    return record


def _raw(body: str, *, handle: str = "someone", videos: bool = False) -> str:
    """A minimal raw X source markdown with frontmatter."""
    lines = ["---", "author: Some One", f"author_handle: {handle}"]
    if videos:
        lines += ["videos:", "  - page: https://x.com/x/status/1/video/1", "    transcript: t.txt"]
    lines += ["---", "", body, ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# build_scaffold
# --------------------------------------------------------------------------- #
def test_build_scaffold_has_frontmatter_quote_and_stubs() -> None:
    record = _record("123456")
    page = wiki_pages.build_scaffold(record, _raw("Hello world tweet."), ingested_date="2026-06-29")

    assert 'tweet_id: "123456"' in page
    assert "author_handle: someone" in page
    assert "domain: ai-swe" in page
    assert "raw: raw/x/likes/123456.md" in page
    # OKF reserved frontmatter: type/title/resource/timestamp/tags.
    assert "type: source" in page
    assert f'title: "{wiki_pages.TITLE_PLACEHOLDER}"' in page
    assert "resource: https://x.com/someone/status/123456" in page
    assert "timestamp: 2026-06-29" in page
    assert "tags: []" in page
    # The legacy key names are gone.
    assert "source_url:" not in page
    assert "ingested:" not in page
    assert "> Hello world tweet." in page
    assert "**Source:** [@someone on X](https://x.com/someone/status/123456)" in page
    assert wiki_pages.SCAFFOLD_SENTINEL in page
    assert "## Summary" in page and "## Entities" in page and "## Concepts" in page


def test_build_scaffold_flags_untranscribed_video() -> None:
    record = _record("999000", has_video=True)
    page = wiki_pages.build_scaffold(record, _raw("clip"), ingested_date="2026-06-29")

    assert "has_video: true" in page
    assert "video_transcribed: false" in page
    assert "not yet transcribed" in page


def test_build_scaffold_marks_transcribed_video_without_warning() -> None:
    record = _record("999001", has_video=True)
    page = wiki_pages.build_scaffold(record, _raw("clip", videos=True), ingested_date="2026-06-29")

    assert "video_transcribed: true" in page
    assert "not yet transcribed" not in page


# --------------------------------------------------------------------------- #
# scaffold_one
# --------------------------------------------------------------------------- #
def _seed_raw(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, record: dict[str, Any]) -> Path:
    """Point WIKI_RAW at tmp_path/raw and write the record's raw source there."""
    monkeypatch.setenv("WIKI_RAW", str(tmp_path / "raw"))
    raw_path = tmp_path / str(record["file"])
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(_raw("Body text."), encoding="utf-8")
    return raw_path


def test_scaffold_one_writes_new_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record = _record("111111")
    _seed_raw(monkeypatch, tmp_path, record)
    vault = tmp_path / "wiki"

    status, page = wiki_pages.scaffold_one(
        record, ingested_date="2026-06-29", vault=vault, dry_run=False, force=False
    )

    assert status == "written"
    assert page.exists()
    assert wiki_pages.SCAFFOLD_SENTINEL in page.read_text(encoding="utf-8")


def test_scaffold_one_refuses_to_clobber_filled_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record("222222")
    _seed_raw(monkeypatch, tmp_path, record)
    vault = tmp_path / "wiki"
    page = vault / record["wiki_page"]
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# Real title\n\nFully written content.\n", encoding="utf-8")

    status, _ = wiki_pages.scaffold_one(
        record, ingested_date="2026-06-29", vault=vault, dry_run=False, force=False
    )

    assert status == "skip-filled"
    assert page.read_text(encoding="utf-8") == "# Real title\n\nFully written content.\n"


def test_scaffold_one_rewrites_existing_stub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record("333333")
    _seed_raw(monkeypatch, tmp_path, record)
    vault = tmp_path / "wiki"

    wiki_pages.scaffold_one(
        record, ingested_date="2026-06-29", vault=vault, dry_run=False, force=False
    )
    status, _ = wiki_pages.scaffold_one(
        record, ingested_date="2026-06-30", vault=vault, dry_run=False, force=False
    )

    assert status == "rewritten"


def test_scaffold_one_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record("444444")
    _seed_raw(monkeypatch, tmp_path, record)
    vault = tmp_path / "wiki"

    status, page = wiki_pages.scaffold_one(
        record, ingested_date="2026-06-29", vault=vault, dry_run=True, force=False
    )

    assert status == "would-write"
    assert not page.exists()


# --------------------------------------------------------------------------- #
# log-append
# --------------------------------------------------------------------------- #
def test_build_log_entry_shape() -> None:
    entry = wiki_pages.build_log_entry(
        "ingest", "Some title", "2026-06-29", ["did a thing", "did another"], "x.md, y.md"
    )

    assert entry.startswith("## [2026-06-29] ingest | Some title\n\n")
    assert "- did a thing\n" in entry
    assert entry.rstrip().endswith("- Pages touched: x.md, y.md")


def test_append_log_creates_and_separates(tmp_path: Path) -> None:
    vault = tmp_path / "wiki"
    vault.mkdir()
    entry = wiki_pages.build_log_entry("lint", "Pass", "2026-06-29", ["ok"], None)

    log = wiki_pages.append_log(vault, entry, dry_run=False)
    wiki_pages.append_log(vault, entry, dry_run=False)

    text = log.read_text(encoding="utf-8")
    assert text.startswith("# Log\n\n## [2026-06-29] lint | Pass")
    assert text.count("## [2026-06-29] lint | Pass") == 2
    assert "\n\n## [2026-06-29] lint | Pass" in text.split("# Log", 1)[1]


def test_append_log_dry_run_writes_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "wiki"
    vault.mkdir()
    entry = wiki_pages.build_log_entry("query", "Q", "2026-06-29", ["a"], None)

    log = wiki_pages.append_log(vault, entry, dry_run=True)

    assert not log.exists()


# --------------------------------------------------------------------------- #
# index-add
# --------------------------------------------------------------------------- #
_INDEX = (
    "# Index\n\n"
    "## Sources\n\n"
    "### Skills\n\n"
    "- [Existing](sources/existing.md) — already here.\n\n"
    "## Concepts\n\n"
    "- [A concept](concepts/a.md)\n"
)


def test_insert_index_entry_appends_after_last_bullet() -> None:
    new_text, status = wiki_pages.insert_index_entry(
        _INDEX, "Skills", "[New](sources/new.md) — fresh."
    )

    assert status == "inserted"
    lines = new_text.splitlines()
    skills_idx = lines.index("### Skills")
    # New bullet lands right after the existing one, before the next heading.
    assert lines[skills_idx + 2] == "- [Existing](sources/existing.md) — already here."
    assert lines[skills_idx + 3] == "- [New](sources/new.md) — fresh."


def test_insert_index_entry_dedupes_on_link_target() -> None:
    new_text, status = wiki_pages.insert_index_entry(
        _INDEX, "Skills", "[Existing again](sources/existing.md) — dupe link."
    )

    assert status == "duplicate"
    assert new_text == _INDEX


def test_insert_index_entry_matches_top_level_section() -> None:
    new_text, status = wiki_pages.insert_index_entry(
        _INDEX, "Concepts", "[B concept](concepts/b.md)"
    )

    assert status == "inserted"
    assert "- [B concept](concepts/b.md)" in new_text


def test_insert_index_entry_unknown_section_raises() -> None:
    with pytest.raises(ValueError, match="section heading not found"):
        wiki_pages.insert_index_entry(_INDEX, "Nope", "[X](x.md)")


def test_link_target_extracts_path() -> None:
    assert wiki_pages.link_target("[T](sources/x.md) — s") == "sources/x.md"
    assert wiki_pages.link_target("no link here") is None


# --------------------------------------------------------------------------- #
# migrate-okf
# --------------------------------------------------------------------------- #
LEGACY_SOURCE = """\
---
type: source
tweet_id: "111"
author_handle: a
domain: ai-swe
source_url: https://x.com/a/status/111
raw: raw/x/likes/111.md
ingested: 2026-06-29
has_video: false
video_transcribed: false
---

# A crafted headline

> quote

body
"""


def test_migrate_source_renames_and_adds_okf_keys() -> None:
    migrated, changed = wiki_pages.migrate_source_text(LEGACY_SOURCE)
    assert changed is True
    assert "resource: https://x.com/a/status/111" in migrated
    assert "timestamp: 2026-06-29" in migrated
    assert "source_url:" not in migrated
    assert "ingested:" not in migrated
    # `title` is derived from the H1 and inserted after `type:`.
    assert 'title: "A crafted headline"' in migrated
    assert "tags: []" in migrated
    # The body survives unchanged.
    assert "> quote" in migrated and "body" in migrated


def test_migrate_source_is_idempotent() -> None:
    once, _ = wiki_pages.migrate_source_text(LEGACY_SOURCE)
    twice, changed = wiki_pages.migrate_source_text(once)
    assert changed is False
    assert twice == once


def test_migrate_source_without_h1_uses_placeholder() -> None:
    no_h1 = LEGACY_SOURCE.replace("# A crafted headline\n\n", "")
    migrated, changed = wiki_pages.migrate_source_text(no_h1)
    assert changed is True
    assert f'title: "{wiki_pages.TITLE_PLACEHOLDER}"' in migrated


def test_migrate_source_without_frontmatter_is_noop() -> None:
    plain = "# Just a heading\n\nbody\n"
    migrated, changed = wiki_pages.migrate_source_text(plain)
    assert changed is False
    assert migrated == plain


def test_migrate_comparison_prepends_frontmatter() -> None:
    plain = "# A vs B\n\nbody\n"
    migrated, changed = wiki_pages.migrate_comparison_text(plain)
    assert changed is True
    assert migrated.startswith("---\n")
    assert "type: comparison" in migrated
    assert 'title: "A vs B"' in migrated
    assert "tags: []" in migrated
    assert "# A vs B" in migrated and "body" in migrated


def test_migrate_comparison_fills_missing_keys() -> None:
    partial = '---\ntitle: "Kept"\n---\n\n# A vs B\n\nbody\n'
    migrated, changed = wiki_pages.migrate_comparison_text(partial)
    assert changed is True
    assert "type: comparison" in migrated
    assert 'title: "Kept"' in migrated  # existing title is preserved
    assert "tags: []" in migrated


def test_migrate_comparison_is_idempotent() -> None:
    once, _ = wiki_pages.migrate_comparison_text("# A vs B\n\nbody\n")
    twice, changed = wiki_pages.migrate_comparison_text(once)
    assert changed is False
    assert twice == once


def test_cmd_migrate_okf_rewrites_vault_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "wiki"
    (vault / "sources").mkdir(parents=True)
    (vault / "comparisons").mkdir(parents=True)
    (vault / "sources" / "source-111.md").write_text(LEGACY_SOURCE, encoding="utf-8")
    (vault / "comparisons" / "a-vs-b.md").write_text("# A vs B\n\nbody\n", encoding="utf-8")

    args = argparse.Namespace(
        config=tmp_path / "ingest_config.json",
        domain="ai-swe",
        vault=vault,
        dry_run=False,
    )
    monkeypatch.setattr(ingest_plan, "load_json", lambda _path: {})

    code = wiki_pages.cmd_migrate_okf(args)
    assert code == wiki_pages.EXIT_SUCCESS

    source_out = (vault / "sources" / "source-111.md").read_text(encoding="utf-8")
    assert "resource: https://x.com/a/status/111" in source_out
    assert "timestamp: 2026-06-29" in source_out
    comparison_out = (vault / "comparisons" / "a-vs-b.md").read_text(encoding="utf-8")
    assert "type: comparison" in comparison_out


def test_cmd_migrate_okf_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "wiki"
    (vault / "sources").mkdir(parents=True)
    (vault / "sources" / "source-111.md").write_text(LEGACY_SOURCE, encoding="utf-8")

    args = argparse.Namespace(
        config=tmp_path / "ingest_config.json",
        domain="ai-swe",
        vault=vault,
        dry_run=True,
    )
    monkeypatch.setattr(ingest_plan, "load_json", lambda _path: {})

    code = wiki_pages.cmd_migrate_okf(args)
    assert code == wiki_pages.EXIT_SUCCESS
    # The on-disk page is untouched in a dry run.
    assert (vault / "sources" / "source-111.md").read_text(encoding="utf-8") == LEGACY_SOURCE
