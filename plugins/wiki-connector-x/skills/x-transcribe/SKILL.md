---
name: x-transcribe
description: "Backfill local ASR transcripts for caption-less X videos in raw/x/ so their spoken content becomes ingestible. USE WHEN: the user wants to transcribe X videos, backfill missing captions or transcripts, or make video sources searchable before ingest; or asks why a video source has no transcript. Covers the transcribe worklist, the local faster-whisper run, output paths, and idempotency controls."
user-invocable: true
metadata:
  spec_version: "1.0"
  last_updated: "2026-06-28"
---

# X Transcribe Skill

## Overview

This skill backfills ASR (speech-to-text) transcripts for X videos that X did not caption, using **local** faster-whisper — local-only for privacy and zero cost. It writes transcript text into `raw/assets/` and patches the source's frontmatter so the spoken content is available to the **wiki-ingest** skill. Per [AGENTS.md](../../../../AGENTS.md), the source markdown is otherwise immutable; this skill adds only the `transcript:` linkage and an Attachments entry.

This is a pre-ingest step: a video source with no transcript carries no ingestible spoken content. Run this before ingesting such sources.

## Worklist

The worklist is sources in the ingest manifest (`<vault>/.wiki_index/ingest_state.json`) with `status=ingested` and `has_video`, whose domain is enabled in the ingest config (`<vault>/.wiki_index/ingest_config.json`), that carry a `videos[]` entry lacking a `transcript`. Size the job first — it writes nothing in dry-run:

```bash
uv run x-transcribe --dry-run
```

## Running the transcription

For each worklist video the script downloads the MP4 stream to a temp file, transcribes locally, writes the transcript, patches the source, then deletes the temp MP4.

```bash
uv run x-transcribe                 # process the worklist
uv run x-transcribe --id 123        # single tweet id
uv run x-transcribe --limit 5       # cap the batch
uv run x-transcribe --model medium  # base | small (default) | medium
uv run x-transcribe --all-domains   # ignore domain gating
```

It is idempotent — videos that already have a transcript are skipped unless you pass `--force` to re-download and re-transcribe.

## Output

For tweet id `<id>` and video index `<idx>`, the script:

- writes `raw/assets/x/<id>/video-<idx>-transcript.txt`;
- patches the source frontmatter `videos[].transcript:` to point at that file;
- adds the transcript to the source's Attachments section.

This matches the `videos[].transcript` contract documented in the **x-import** skill and AGENTS.md.

## Boundaries

- Local-only ASR. No transcript audio or video is committed; MP4s are temp files, deleted after transcription.
- The only edits to a `raw/` source are the `transcript:` frontmatter line and the Attachments entry — the source body stays immutable.
- Hand-offs: importing the X sources in the first place is the **x-import** skill; folding the now-transcribed sources into the wiki is the **wiki-ingest** skill.
