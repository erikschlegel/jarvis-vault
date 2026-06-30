"""Download tweet media, linked articles, and video transcripts into raw/assets/x/."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from wiki_connector_x.x_source_io import slugify
from wiki_core import paths

RAW_ASSETS_X = paths.raw_root() / "assets" / "x"
USER_AGENT = "jarvis-vault/1.0 (personal archive)"

X_STATUS_RE = re.compile(
    r"^https?://(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/\d+",
    re.I,
)
SUBTITLE_URI_RE = re.compile(r'URI="([^"]+)"')


def tweet_asset_dir(tweet_id: str) -> Path:
    return RAW_ASSETS_X / tweet_id


def fetch_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return cast(bytes, resp.read())


def fetch_text(url: str, timeout: int = 60) -> str:
    return fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def download_file(url: str, dest: Path, dry_run: bool) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return False
    if dry_run:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = fetch_bytes(url)
    dest.write_bytes(data)
    return True


def media_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    media = payload.get("includes", {}).get("media", [])
    return {m["media_key"]: m for m in media}


def best_mp4_url(media: dict[str, Any]) -> str | None:
    variants = media.get("variants") or []
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and v.get("url")]
    if not mp4s:
        return None
    mp4s.sort(key=lambda v: v.get("bit_rate") or 0, reverse=True)
    return cast(str, mp4s[0]["url"])


def m3u8_url(media: dict[str, Any]) -> str | None:
    for variant in media.get("variants") or []:
        if variant.get("content_type") == "application/x-mpegURL" and variant.get("url"):
            return cast(str, variant["url"])
    return None


def subtitle_vtt_url(media: dict[str, Any]) -> str | None:
    playlist_url = m3u8_url(media)
    if not playlist_url:
        return None
    try:
        master = fetch_text(playlist_url)
    except (urllib.error.URLError, TimeoutError):
        return None
    base = playlist_url.rsplit("/", 1)[0] + "/"
    for line in master.splitlines():
        if "TYPE=SUBTITLES" not in line:
            continue
        match = SUBTITLE_URI_RE.search(line)
        if not match:
            continue
        sub_playlist = urllib.parse.urljoin(base, match.group(1))
        try:
            sub_text = fetch_text(sub_playlist)
        except (urllib.error.URLError, TimeoutError):
            continue
        for sub_line in sub_text.splitlines():
            sub_line = sub_line.strip()
            if sub_line.startswith("/subtitles/") and sub_line.endswith(".vtt"):
                return "https://video.twimg.com" + sub_line
            if sub_line.endswith(".vtt") and not sub_line.startswith("#"):
                return cast(str, urllib.parse.urljoin(sub_playlist, sub_line))
    return None


def vtt_to_text(vtt: str) -> str:
    """Convert WebVTT (including X's <X-word-ms> captions) to readable plain text."""
    if "<X-word-ms" in vtt or "<x-word-ms" in vtt:
        chunks = re.findall(r"<X-word-ms[^>]*>(.*?)</X-word-ms>", vtt, flags=re.I | re.S)
        if chunks:
            return "\n".join(html.unescape(c).strip() for c in chunks if c.strip())
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT":
            continue
        if "-->" in line or line.isdigit():
            continue
        if line.startswith("NOTE") or line.startswith("STYLE"):
            continue
        lines.append(html.unescape(re.sub(r"<[^>]+>", "", line)).strip())
    return "\n".join(lines)


def is_article_url(url: str) -> bool:
    if not url.startswith("http"):
        return False
    if X_STATUS_RE.match(url):
        return False
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host in ("t.co",):
        return False
    if host.endswith("x.com") or host.endswith("twitter.com"):
        if "/photo/" in path or "/video/" in path or "/status/" in path:
            return False
        return False
    return True


def video_url_for_media(tweet: dict[str, Any], media_key: str) -> str | None:
    blocks = (
        tweet.get("entities") or {},
        (tweet.get("note_tweet") or {}).get("entities") or {},
    )
    for block in blocks:
        for item in block.get("urls") or []:
            if item.get("media_key") == media_key:
                return cast("str | None", item.get("expanded_url") or item.get("url"))
    return None


def article_urls_from_tweet(tweet: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    blocks = (
        tweet.get("entities") or {},
        (tweet.get("note_tweet") or {}).get("entities") or {},
    )
    for block in blocks:
        for item in block.get("urls") or []:
            candidate = item.get("unwound_url") or item.get("expanded_url") or item.get("url")
            if candidate and is_article_url(candidate) and candidate not in urls:
                urls.append(candidate)
    return urls


def extract_html_article(page: str) -> tuple[str, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    title = (
        html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
        if title_match
        else "article"
    )
    og_desc = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        page,
        re.I,
    )
    chunks: list[str] = []
    if og_desc:
        chunks.append(html.unescape(og_desc.group(1)).strip())
    for match in re.finditer(r"<p[^>]*>(.*?)</p>", page, re.I | re.S):
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if len(text) > 40:
            chunks.append(text)
    body = "\n\n".join(dict.fromkeys(chunks))
    return title, body or "_Could not extract article body; see article.html._"


def tweet_text(tweet: dict[str, Any]) -> str:
    note = tweet.get("note_tweet") or {}
    return (note.get("text") or tweet.get("text") or "").strip()


def native_article_text(tweet: dict[str, Any]) -> str | None:
    article = tweet.get("article")
    if not article:
        return None
    if isinstance(article, dict):
        for key in ("plain_text", "text", "title"):
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    if isinstance(article, str):
        return article.strip()
    return None


def process_tweet_assets(
    tweet: dict[str, Any],
    media_by_key: dict[str, dict[str, Any]],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Return manifest paths (repo-relative) and download assets."""
    tweet_id = tweet["id"]
    dest = tweet_asset_dir(tweet_id)
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"media": [], "videos": [], "articles": [], "transcripts": []}

    keys = (tweet.get("attachments") or {}).get("media_keys") or []
    for idx, key in enumerate(keys, start=1):
        media = media_by_key.get(key)
        if not media:
            continue
        media_type = media.get("type", "unknown")
        if media_type == "photo" and media.get("url"):
            ext = ".jpg"
            if ".png" in media["url"]:
                ext = ".png"
            filename = f"image-{idx}{ext}"
            path = dest / filename
            if download_file(media["url"], path, dry_run):
                manifest["media"].append(_rel(path))
            alt = media.get("alt_text")
            if alt:
                alt_path = dest / f"image-{idx}.alt.txt"
                if not alt_path.exists() and not dry_run:
                    alt_path.write_text(alt, encoding="utf-8")
        elif media_type in {"video", "animated_gif"}:
            page_url = video_url_for_media(tweet, key)
            stream_url = best_mp4_url(media)
            transcript_rel: str | None = None
            vtt_url = subtitle_vtt_url(media)
            if vtt_url:
                transcript_path = dest / f"video-{idx}-transcript.txt"
                if (
                    not transcript_path.exists() or transcript_path.stat().st_size == 0
                ) and not dry_run:
                    try:
                        vtt = fetch_text(vtt_url)
                        transcript_path.write_text(vtt_to_text(vtt), encoding="utf-8")
                    except (urllib.error.URLError, TimeoutError):
                        pass
                if transcript_path.exists() and transcript_path.stat().st_size > 0:
                    transcript_rel = _rel(transcript_path)
                    if transcript_rel not in manifest["transcripts"]:
                        manifest["transcripts"].append(transcript_rel)
            entry = {
                "page": page_url or stream_url,
                "stream": stream_url,
                "transcript": transcript_rel,
            }
            if entry["page"] or entry["stream"]:
                manifest["videos"].append(entry)

    native = native_article_text(tweet)
    if native:
        article_path = dest / "x-article.md"
        if not article_path.exists() and not dry_run:
            article_path.write_text(native, encoding="utf-8")
        if article_path.exists() or dry_run:
            manifest["articles"].append(_rel(article_path))

    for url_idx, url in enumerate(article_urls_from_tweet(tweet), start=1):
        slug = slugify(urllib.parse.urlparse(url).netloc + "-" + str(url_idx), 48)
        html_path = dest / f"article-{slug}.html"
        md_path = dest / f"article-{slug}.md"
        if md_path.exists() and md_path.stat().st_size > 0:
            manifest["articles"].append(_rel(md_path))
            continue
        if dry_run:
            manifest["articles"].append(_rel(md_path))
            continue
        try:
            page = fetch_text(url)
        except (urllib.error.URLError, TimeoutError, urllib.error.HTTPError):
            continue
        if not dry_run:
            html_path.write_text(page, encoding="utf-8")
            title, body = extract_html_article(page)
            md_path.write_text(f"# {title}\n\nSource: {url}\n\n{body}\n", encoding="utf-8")
        manifest["articles"].append(_rel(md_path))

    return manifest


def _rel(path: Path) -> str:
    return str(path.relative_to(paths.raw_root().parent))
