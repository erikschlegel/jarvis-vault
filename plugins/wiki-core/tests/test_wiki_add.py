"""Hermetic tests for the generic ``wiki-add`` on-ramp.

These exercise the pure helpers (identity hashing, HTML reduction, inbox
rendering) and the file-writing ``add_source`` against a ``tmp_path`` inbox,
without any network access — URL fetching is monkeypatched.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from wiki_core import wiki_add


def test_is_url_discriminates() -> None:
    assert wiki_add.is_url("https://example.com") is True
    assert wiki_add.is_url("http://example.com") is True
    assert wiki_add.is_url("/local/file.md") is False


def test_strip_html_removes_scripts_and_tags() -> None:
    raw = (
        "<html><head><style>a{}</style></head>"
        "<body><p>Hello &amp; bye</p><script>x()</script></body></html>"
    )
    text = wiki_add._strip_html(raw)
    assert "Hello & bye" in text
    assert "a{}" not in text
    assert "x()" not in text
    assert "<p>" not in text


def test_extract_title() -> None:
    assert wiki_add._extract_title("<title> A  Page </title>") == "A Page"
    assert wiki_add._extract_title("<html>no title</html>") == ""


def test_source_id_web_hashes_url() -> None:
    a = wiki_add.source_id_for(source_type="web", resource="https://x/y", body="", stem="s")
    b = wiki_add.source_id_for(source_type="web", resource="https://x/y", body="diff", stem="s")
    assert a == b  # URL-stable across body changes
    assert len(a) == 16


def test_source_id_doc_hashes_body_then_stem() -> None:
    from_body = wiki_add.source_id_for(source_type="doc", resource="", body="content", stem="s")
    assert len(from_body) == 16
    from_stem = wiki_add.source_id_for(source_type="doc", resource="", body="   ", stem="mystem")
    assert from_stem == "mystem"


def test_render_inbox_md_shape() -> None:
    md = wiki_add.render_inbox_md(
        source_type="doc",
        source_id="abc123",
        resource="file:///x.md",
        title="A Title",
        imported_at="2026-07-01",
        body="Body text.",
    )
    assert md.startswith("---\n")
    assert "source_type: doc" in md
    assert 'source_id: "abc123"' in md
    assert 'resource: "file:///x.md"' in md
    assert 'title: "A Title"' in md
    assert "imported_at: 2026-07-01" in md
    assert md.rstrip().endswith("Body text.")


def test_add_source_local_file(tmp_path: Path) -> None:
    src = tmp_path / "note.md"
    src.write_text("Local note body.", encoding="utf-8")
    inbox = tmp_path / "raw" / "inbox"

    result = wiki_add.add_source(str(src), title=None, imported_at="2026-07-01", inbox=inbox)

    assert result.path.exists()
    assert result.path.parent == inbox
    assert len(result.source_id) == 16
    text = result.path.read_text(encoding="utf-8")
    assert "source_type: doc" in text
    assert "Local note body." in text
    assert src.resolve().as_uri() in text


def test_add_source_url_monkeypatched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wiki_add, "fetch_url", lambda url: ("Fetched Title", "Page body."))
    inbox = tmp_path / "raw" / "inbox"

    result = wiki_add.add_source(
        "https://example.com/post", title=None, imported_at="2026-07-01", inbox=inbox
    )

    text = result.path.read_text(encoding="utf-8")
    assert "source_type: web" in text
    assert 'resource: "https://example.com/post"' in text
    assert 'title: "Fetched Title"' in text
    assert "Page body." in text


def test_add_source_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        wiki_add.add_source(
            str(tmp_path / "nope.md"),
            title=None,
            imported_at="2026-07-01",
            inbox=tmp_path / "inbox",
        )


def test_derive_title_prefers_h1_then_first_line() -> None:
    assert wiki_add.derive_title("# Heading\nrest of body") == "Heading"
    assert wiki_add.derive_title("plain first line\nmore") == "plain first line"
    assert wiki_add.derive_title("   \n\n") == ""


def test_add_text_lands_content_with_derived_title(tmp_path: Path) -> None:
    inbox = tmp_path / "raw" / "inbox"

    result = wiki_add.add_text(
        "# My Note\n\nBody here.", title=None, imported_at="2026-07-01", inbox=inbox
    )

    assert result.path.exists()
    assert result.path.parent == inbox
    assert len(result.source_id) == 16
    text = result.path.read_text(encoding="utf-8")
    assert "source_type: doc" in text
    assert 'resource: ""' in text
    assert 'title: "My Note"' in text
    assert "Body here." in text


def test_add_text_uses_explicit_title_and_hashes_body(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    a = wiki_add.add_text("same body", title="T", imported_at="2026-07-01", inbox=inbox)
    b = wiki_add.add_text("same body", title="T", imported_at="2026-07-01", inbox=inbox)
    assert a.source_id == b.source_id  # content-hash identity is stable
    assert 'title: "T"' in a.path.read_text(encoding="utf-8")


def test_add_text_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        wiki_add.add_text("   \n\n", title=None, imported_at="2026-07-01", inbox=tmp_path)


def test_main_stdin_writes_and_returns_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inbox = tmp_path / "inbox"
    monkeypatch.setattr("sys.stdin", io.StringIO("Piped body text."))

    rc = wiki_add.main(
        ["--stdin", "--title", "Piped", "--inbox", str(inbox), "--date", "2026-07-01"]
    )

    assert rc == wiki_add.EXIT_SUCCESS
    files = list(inbox.glob("*.md"))
    assert len(files) == 1
    assert "Piped body text." in files[0].read_text(encoding="utf-8")


def test_main_text_writes_and_returns_success(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    rc = wiki_add.main(["--text", "# Pasted\nbody", "--inbox", str(inbox), "--date", "2026-07-01"])
    assert rc == wiki_add.EXIT_SUCCESS
    assert len(list(inbox.glob("*.md"))) == 1


def test_main_conflicting_inputs_fail(tmp_path: Path) -> None:
    rc = wiki_add.main(["src.md", "--stdin", "--inbox", str(tmp_path)])
    assert rc == wiki_add.EXIT_FAILURE


def test_main_no_input_fails(tmp_path: Path) -> None:
    rc = wiki_add.main(["--inbox", str(tmp_path)])
    assert rc == wiki_add.EXIT_FAILURE
