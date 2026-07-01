#!/usr/bin/env python3
"""Backfill ASR transcripts for caption-less X videos using local faster-whisper.

Worklist: sources in ingest_state.json with status=ingested + has_video, whose
domain is enabled in ingest_config.json, that carry a videos[] entry lacking a
transcript. For each, download the mp4 stream to a temp file, transcribe locally,
write raw/assets/x/<id>/video-<idx>-transcript.txt, patch the source frontmatter
(transcript: line) + Attachments section, then delete the temp mp4.

Local-only (privacy + free). Idempotent: skips videos that already have a
transcript unless --force. A video that turns out to carry no transcribable
audio (silent screen recording, or music-only with no speech) gets a sidecar
video-<idx>-skip.txt marker so it drops out of the worklist instead of being
re-downloaded on every run. Run --dry-run first to size the job.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import urllib.error
from pathlib import Path
from typing import Any

from wiki_connector_x.x_tweet_assets import download_file, tweet_asset_dir
from wiki_core import paths

STATE_PATH = paths.state_path()
CONFIG_PATH = paths.config_path()
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def enabled_domains() -> set[str]:
    if not CONFIG_PATH.exists():
        return {"ai-swe"}
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    domains = cfg.get("domains", {})
    return {name for name, spec in domains.items() if spec.get("enabled")}


def parse_videos(text: str) -> list[dict[str, Any]]:
    """Parse the videos: frontmatter block into ordered dicts."""
    m = FM_RE.match(text)
    if not m:
        return []
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_block = False
    for line in m.group(1).splitlines():
        if re.match(r"^videos:\s*$", line):
            in_block = True
            continue
        if not in_block:
            continue
        if re.match(r"^\S", line):  # de-indented -> block ended
            break
        stripped = line.strip()
        if stripped.startswith("- page:") or stripped == "-":
            if cur:
                out.append(cur)
            cur = {}
            mp = re.search(r'- page:\s*"?([^"]+?)"?\s*$', stripped)
            if mp:
                cur["page"] = mp.group(1)
        elif stripped.startswith("stream:") and cur is not None:
            ms = re.search(r'stream:\s*"?([^"]+?)"?\s*$', stripped)
            if ms:
                cur["stream"] = ms.group(1)
        elif stripped.startswith("transcript:") and cur is not None:
            mt = re.search(r'transcript:\s*"?([^"]+?)"?\s*$', stripped)
            if mt:
                cur["transcript"] = mt.group(1)
    if cur:
        out.append(cur)
    return out


def skip_marker_path(tid: str, idx: int) -> Path:
    """Sidecar marker recording a video that yielded no transcribable audio."""
    return tweet_asset_dir(tid) / f"video-{idx}-skip.txt"


def build_worklist(
    domains: set[str], only_id: str | None, ignore_markers: bool = False
) -> list[dict[str, Any]]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    for tid, meta in state["sources"].items():
        if only_id and tid != only_id:
            continue
        if meta.get("status") != "ingested" or not meta.get("has_video"):
            continue
        if not only_id and meta.get("domain") not in domains:
            continue
        src = paths.raw_root().parent / meta["file"]
        if not src.exists():
            continue
        videos = parse_videos(src.read_text(encoding="utf-8"))
        for idx, vid in enumerate(videos, start=1):
            if vid.get("transcript") or not vid.get("stream"):
                continue
            if not ignore_markers and skip_marker_path(tid, idx).exists():
                continue
            items.append(
                {
                    "tweet_id": tid,
                    "file": src,
                    "idx": idx,
                    "stream": vid["stream"],
                    "domain": meta.get("domain"),
                }
            )
    return items


def write_skip_marker(tid: str, idx: int, reason: str) -> None:
    """Record that a video has no transcribable audio so it leaves the worklist."""
    p = skip_marker_path(tid, idx)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{reason}\n", encoding="utf-8")


def probe_has_audio(path: Path) -> bool:
    """True if the media file contains at least one audio stream."""
    import av  # lazy import; faster-whisper already pulls in PyAV

    try:
        with av.open(str(path)) as container:
            return any(s.type == "audio" for s in container.streams)
    except Exception:  # noqa: BLE001
        return False


def patch_source(src: Path, idx: int, stream: str, transcript_rel: str) -> None:
    """Insert transcript: into the frontmatter video entry + Attachments line."""
    lines = src.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        out.append(line)
        # frontmatter: after the matching stream line, add transcript line
        if line.strip().startswith("stream:") and stream in line:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if not nxt.startswith("transcript:"):
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f'{indent}transcript: "{transcript_rel}"')
        # Attachments: after the matching video stream bullet, add transcript bullet
        if line.startswith("- Video stream:") and stream in line:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if not nxt.startswith("- Video transcript:"):
                out.append(f"- Video transcript: `{transcript_rel}`")
    src.write_text("\n".join(out) + "\n", encoding="utf-8")


def reconcile_frontmatter(src: Path, idx: int, stream: str, transcript_rel: str) -> bool:
    """Patch the frontmatter transcript: line when the transcript file already exists.

    build_worklist only surfaces videos whose frontmatter lacks a transcript: line,
    but the processing loop skips when the transcript *file* is on disk. Those two
    criteria can diverge (e.g. a git pull restores frontmatter while raw/assets
    persists), stranding the source in the worklist forever. Calling this on the
    file-exists path re-patches the frontmatter (idempotently) so the source drops
    out of the worklist. Returns True if a change was written.
    """
    before = src.read_text(encoding="utf-8")
    patch_source(src, idx, stream, transcript_rel)
    return src.read_text(encoding="utf-8") != before


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list worklist, write nothing")
    ap.add_argument("--all-domains", action="store_true", help="ignore domain gating")
    ap.add_argument("--id", dest="only_id", help="transcribe a single tweet id")
    ap.add_argument("--limit", type=int, default=0, help="cap number of videos")
    ap.add_argument("--model", default="small", help="whisper model size (base|small|medium)")
    ap.add_argument("--force", action="store_true", help="re-download/transcribe even if present")
    args = ap.parse_args()

    domains = _all_domains() if args.all_domains else enabled_domains()
    worklist = build_worklist(domains, args.only_id, ignore_markers=args.force)
    if args.limit:
        worklist = worklist[: args.limit]

    print(
        f"worklist: {len(worklist)} caption-less video(s); "
        f"domains={sorted(domains)}; model={args.model}"
    )
    for item in worklist:
        print(f"  {item['tweet_id']} [{item['domain']}] v{item['idx']}  {item['file'].name}")
    if args.dry_run or not worklist:
        return 0

    from faster_whisper import WhisperModel  # lazy import

    print(f"\nloading faster-whisper model '{args.model}' (cpu/int8)...")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    done = 0
    reconciled = 0
    for item in worklist:
        tid, idx, stream, src = item["tweet_id"], item["idx"], item["stream"], item["file"]
        transcript_path = tweet_asset_dir(tid) / f"video-{idx}-transcript.txt"
        transcript_rel = str(transcript_path.relative_to(paths.raw_root().parent))
        if transcript_path.exists() and transcript_path.stat().st_size > 0 and not args.force:
            if reconcile_frontmatter(src, idx, stream, transcript_rel):
                reconciled += 1
                print(f"reconcile {tid} v{idx}: transcript file existed, patched frontmatter")
            else:
                print(f"skip {tid} v{idx} (transcript exists)")
            continue
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
            tmp_path = Path(tmp.name)
            try:
                download_file(stream, tmp_path, dry_run=False)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                print(f"FAIL download {tid} v{idx}: {exc}")
                continue
            if not probe_has_audio(tmp_path):
                write_skip_marker(tid, idx, "no audio stream (silent video)")
                print(f"skip {tid} v{idx}: no audio stream (silent video) — marked")
                continue
            print(
                f"transcribe {tid} v{idx} ({tmp_path.stat().st_size / 1e6:.1f} MB)...", flush=True
            )
            try:
                segments, info = model.transcribe(str(tmp_path), beam_size=5, vad_filter=True)
                text = "\n".join(s.text.strip() for s in segments if s.text.strip())
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL transcribe {tid} v{idx}: {exc}")
                continue
        if not text.strip():
            write_skip_marker(tid, idx, "no speech detected (music-only/ambient)")
            print(f"skip {tid} v{idx}: no speech detected — marked")
            continue
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(text + "\n", encoding="utf-8")
        patch_source(src, idx, stream, transcript_rel)
        done += 1
        print(f"  -> {transcript_rel} ({len(text)} chars, lang={info.language})")

    print(f"\ntranscribed {done}/{len(worklist)} video(s); reconciled {reconciled} frontmatter.")
    return 0


def _all_domains() -> set[str]:
    """Every domain present in the manifest (used by --all-domains)."""
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {m.get("domain") for m in state["sources"].values() if m.get("domain")}


if __name__ == "__main__":
    raise SystemExit(main())
