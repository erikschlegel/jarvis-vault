---
description: Backfill local ASR transcripts for caption-less X videos so they become ingestible.
---

# Transcribe X videos

Run the local transcription backfill per the x-transcribe skill (`plugins/wiki-connector-x/skills/x-transcribe/SKILL.md`).

1. Size the job first with `uv run x-transcribe --dry-run`.
2. Run `uv run x-transcribe` to download each caption-less video stream, transcribe it locally with faster-whisper, write the transcript sidecar under `raw/assets/`, and patch the source frontmatter.

Local-only; writes transcripts into `raw/`, never the vault.
