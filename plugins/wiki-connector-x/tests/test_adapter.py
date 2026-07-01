"""Hermetic tests for the X source adapter.

These exercise ``XAdapter`` directly (identity, body cleaning, resource
resolution, labels, and media flags) plus its scaffold hooks, without the entry
-point registry. A single integration-marked test confirms the core discovers
the adapter through the ``wiki_core.source_adapters`` group when both plugins
are installed editable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_connector_x.adapter import XAdapter


def test_source_id_prefers_explicit_field() -> None:
    adapter = XAdapter()
    assert adapter.source_id({"tweet_id": "123"}, Path("x.md")) == "123"


def test_source_id_falls_back_to_status_url_then_filename() -> None:
    adapter = XAdapter()
    assert adapter.source_id({"post_url": "https://x.com/a/status/456"}, Path("z.md")) == "456"
    assert adapter.source_id({}, Path("789012-note.md")) == "789012"
    assert adapter.source_id({}, Path("plainname.md")) == "plainname"


def test_author_handle_prefers_field_then_url() -> None:
    adapter = XAdapter()
    assert adapter.author_handle({"author_handle": "someone"}) == "someone"
    assert adapter.author_handle({"tweet_url": "https://x.com/other/status/1"}) == "other"
    assert adapter.author_handle({}) == ""


def test_clean_body_strips_boilerplate_and_urls() -> None:
    adapter = XAdapter()
    body = (
        "# Tweet by Some One\n"
        "**Author:** Some One\n"
        "---\n"
        "Real content here https://t.co/abc pic.twitter.com/xyz\n"
        "## Attachments\n"
        "- image.png\n"
    )
    assert adapter.clean_body({}, body) == "Real content here"


def test_resource_url_prefers_fields_then_synthesizes() -> None:
    adapter = XAdapter()
    assert adapter.resource_url({"tweet_url": "https://x.com/a/status/9"}, "9") == (
        "https://x.com/a/status/9"
    )
    assert adapter.resource_url({"author_handle": "bob"}, "77") == "https://x.com/bob/status/77"
    assert adapter.resource_url({}, "88") == "https://x.com/i/status/88"


def test_source_label_uses_handle_or_author() -> None:
    adapter = XAdapter()
    assert adapter.source_label({"author_handle": "someone"}) == "@someone on X"
    assert adapter.source_label({"author": "Some One"}) == "Some One on X"


def test_asset_flags_detect_video_and_transcript() -> None:
    adapter = XAdapter()
    no_video = adapter.asset_flags({}, "no media here")
    assert no_video == {"has_video": False, "video_transcribed": False}

    raw = "videos:\n  - stream: s.mp4\n    transcript: t.txt\n"
    with_video = adapter.asset_flags({}, raw)
    assert with_video == {"has_video": True, "video_transcribed": True}


def test_scaffold_frontmatter_and_notice() -> None:
    adapter = XAdapter()
    record = {"author": "Some One"}
    raw = "videos:\n  - stream: s.mp4\n"  # video present, no transcript
    fm = {"author": "Some One", "author_handle": "someone"}

    lines = adapter.scaffold_frontmatter(record, fm, raw)
    assert "author: Some One" in lines
    assert "author_handle: someone" in lines
    assert "has_video: true" in lines
    assert "video_transcribed: false" in lines

    notices = adapter.scaffold_notices(record, fm, raw)
    assert len(notices) == 1
    assert "not yet transcribed" in notices[0]


def test_owns_claims_raw_x_subtree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WIKI_RAW", str(tmp_path / "raw"))
    adapter = XAdapter()
    assert adapter.owns(tmp_path / "raw" / "x" / "likes" / "1.md", {}) is True
    assert adapter.owns(tmp_path / "raw" / "inbox" / "note.md", {}) is False


def test_owns_claims_by_frontmatter_outside_subtree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WIKI_RAW", str(tmp_path / "raw"))
    adapter = XAdapter()
    path = tmp_path / "raw" / "inbox" / "hand-placed.md"
    assert adapter.owns(path, {"tweet_id": "1"}) is True
    assert adapter.owns(path, {"url": "https://x.com/a/status/2"}) is True


@pytest.mark.integration
def test_entry_point_discovery_registers_x_adapter() -> None:
    from wiki_core import source_adapter

    source_adapter.clear_cache()
    try:
        types = {type(a).__name__ for a in source_adapter.registered_adapters()}
        assert "XAdapter" in types
        assert type(source_adapter.adapter_by_type("x")).__name__ == "XAdapter"
    finally:
        source_adapter.clear_cache()
