"""Hermetic tests for transcribe frontmatter reconciliation.

``reconcile_frontmatter`` covers the divergence between the worklist (which
surfaces videos whose frontmatter lacks a ``transcript:`` line) and the
processing loop's skip check (which keys on the transcript *file* existing).
When the file is already on disk it must patch the frontmatter so the source
drops out of the worklist, idempotently.
"""

from __future__ import annotations

from pathlib import Path

from wiki_connector_x.transcribe_x_videos import reconcile_frontmatter

STREAM = "https://video.twimg.com/amplify_video/1/vid/avc1/720x1280/abc.mp4"
TRANSCRIPT_REL = "raw/assets/x/123/video-1-transcript.txt"


def _source_without_transcript() -> str:
    return (
        "---\n"
        "type: source\n"
        "source_type: x\n"
        "source_id: 123\n"
        "videos:\n"
        '  - page: "https://x.com/a/status/123/video/1"\n'
        f'    stream: "{STREAM}"\n'
        "---\n"
        "\n"
        "Body text.\n"
        "\n"
        "## Attachments\n"
        "\n"
        f"- Video stream: {STREAM}\n"
        "- Video page: https://x.com/a/status/123/video/1\n"
    )


def test_reconcile_patches_missing_frontmatter(tmp_path: Path) -> None:
    src = tmp_path / "source.md"
    src.write_text(_source_without_transcript(), encoding="utf-8")

    changed = reconcile_frontmatter(src, 1, STREAM, TRANSCRIPT_REL)

    assert changed is True
    text = src.read_text(encoding="utf-8")
    assert f'transcript: "{TRANSCRIPT_REL}"' in text
    assert f"- Video transcript: `{TRANSCRIPT_REL}`" in text


def test_reconcile_is_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "source.md"
    src.write_text(_source_without_transcript(), encoding="utf-8")

    assert reconcile_frontmatter(src, 1, STREAM, TRANSCRIPT_REL) is True
    # Second pass finds the transcript already present and writes nothing.
    assert reconcile_frontmatter(src, 1, STREAM, TRANSCRIPT_REL) is False
