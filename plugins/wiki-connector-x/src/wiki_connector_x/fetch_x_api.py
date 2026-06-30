#!/usr/bin/env python3
"""OAuth login and fetch likes/bookmarks from the X API into raw/x/.

Setup (one time):
  1. Copy .env.example → .env and fill X_CLIENT_ID / X_CLIENT_SECRET
  2. In the X developer portal, set callback URL to X_REDIRECT_URI (default below)
  3. App eriks-knowledge-base: Read permissions; OAuth 2.0; scopes:
     tweet.read users.read like.read bookmark.read offline.access
  4. Run: uv run x-fetch login
     If the callback server times out, use the two-step flow:
       uv run x-fetch login --url-only
       # authorize in browser, copy the full redirect URL from the address bar
       uv run x-fetch login --callback 'http://127.0.0.1:8765/callback?...'

Fetch (downloads images, videos, linked articles, and video transcripts):
  uv run x-fetch fetch --likes --bookmarks --months 12

Do not commit .env or .secrets/.
"""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

from wiki_connector_x.x_source_io import (
    RAW_BOOKMARKS,
    RAW_LIKES,
    REPO_ROOT,
    parse_iso_date,
    render_source_md,
    tweet_filename,
    within_months,
    write_if_missing,
)
from wiki_connector_x.x_tweet_assets import media_index, process_tweet_assets, tweet_text

AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
API_BASE = "https://api.twitter.com/2"

SCOPES = [
    "tweet.read",
    "users.read",
    "like.read",
    "bookmark.read",
    "offline.access",
]

MINIMAL_SCOPES = [
    "tweet.read",
    "users.read",
    "offline.access",
]

ENV_PATH = REPO_ROOT / ".env"
SECRETS_DIR = REPO_ROOT / ".secrets"
TOKEN_PATH = SECRETS_DIR / "x_tokens.json"
PENDING_PATH = SECRETS_DIR / "x_oauth_pending.json"

TWEET_FIELDS = (
    "created_at,public_metrics,author_id,text,attachments,entities,"
    "article,note_tweet,media_metadata"
)
USER_FIELDS = "username,name"
EXPANSIONS = "author_id,attachments.media_keys"
MEDIA_FIELDS = "type,url,preview_image_url,variants,alt_text,duration_ms"


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def app_type(env: dict[str, str]) -> str:
    """confidential (Web App) or native (Native App / local PKCE)."""
    return env.get("X_APP_TYPE", "confidential").strip().lower()


def is_native_app(env: dict[str, str]) -> bool:
    return app_type(env) in {"native", "public"}


def require_env() -> dict[str, str]:
    env = load_env(ENV_PATH)
    if not env.get("X_CLIENT_ID"):
        print(
            f"Missing X_CLIENT_ID in {ENV_PATH}.\n"
            "Add values from developer.x.com → eriks-knowledge-base → Keys and tokens.",
            file=sys.stderr,
        )
        sys.exit(2)
    if not is_native_app(env) and not env.get("X_CLIENT_SECRET"):
        print(
            f"Missing X_CLIENT_SECRET in {ENV_PATH} for confidential Web App.\n"
            "For local dev, set X_APP_TYPE=native in .env and use Native App in the portal.",
            file=sys.stderr,
        )
        sys.exit(2)
    env.setdefault("X_REDIRECT_URI", "http://localhost:8765/callback")
    return env


def callback_bind_host(redirect_uri: str) -> str:
    """Listen on loopback even when redirect_uri uses a custom local hostname."""
    host = urllib.parse.urlparse(redirect_uri).hostname or "127.0.0.1"
    if host in {"127.0.0.1", "localhost", "::1"}:
        return host
    return "127.0.0.1"


def warn_if_custom_host_unresolved(redirect_uri: str) -> None:
    host = urllib.parse.urlparse(redirect_uri).hostname or ""
    if host in {"127.0.0.1", "localhost", ""}:
        return
    try:
        import socket

        socket.getaddrinfo(host, None)
    except socket.gaierror:
        print(
            f"Warning: {host} does not resolve. Add to /etc/hosts so the browser can redirect:\n"
            f"  sudo sh -c 'echo \"127.0.0.1 {host}\" >> /etc/hosts'\n"
            "Or copy the redirect URL from the browser bar and run login --callback.",
            flush=True,
        )


def token_request_headers(env: dict[str, str]) -> dict[str, str]:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if not is_native_app(env):
        headers["Authorization"] = basic_auth_header(env["X_CLIENT_ID"], env["X_CLIENT_SECRET"])
    return headers


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{urllib.parse.quote(client_id)}:{urllib.parse.quote(client_secret)}"
    return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")


def post_form(url: str, data: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return cast("dict[str, Any]", json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def api_get(path: str, access_token: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return cast("dict[str, Any]", json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 402:
            raise RuntimeError(
                f"HTTP 402 for {path}: X API credits depleted on your developer account.\n"
                f"{detail}\n"
                "Likes/bookmarks require a paid X API plan with credits, or use fallbacks:\n"
                "  uv run x-import --archive PATH\n"
                "  uv run x-import --bookmarks-json PATH"
            ) from exc
        raise RuntimeError(f"HTTP {exc.code} for {path}: {detail}") from exc


def save_tokens(payload: dict[str, Any]) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)


def load_tokens() -> dict[str, Any]:
    if not TOKEN_PATH.exists():
        print(
            f"No tokens at {TOKEN_PATH}. Run: uv run x-fetch login",
            file=sys.stderr,
        )
        sys.exit(2)
    return cast("dict[str, Any]", json.loads(TOKEN_PATH.read_text(encoding="utf-8")))


def refresh_access_token(env: dict[str, str], tokens: dict[str, Any]) -> dict[str, Any]:
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("No refresh_token; run login again.")
    headers = token_request_headers(env)
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": env["X_CLIENT_ID"],
    }
    refreshed = post_form(TOKEN_URL, data, headers)
    merged = {**tokens, **refreshed}
    save_tokens(merged)
    return merged


def ensure_access_token(env: dict[str, str]) -> str:
    tokens = load_tokens()
    token: str | None = tokens.get("access_token")
    if not token:
        raise RuntimeError("Token file missing access_token; run login again.")
    return token


def login_scopes(minimal: bool) -> list[str]:
    return MINIMAL_SCOPES if minimal else SCOPES


def print_portal_checklist(env: dict[str, str], scopes: list[str]) -> None:
    native = is_native_app(env)
    print("Portal checklist (developer.x.com → eriks-knowledge-base):", flush=True)
    print("  1. User authentication settings → OAuth 2.0 ON", flush=True)
    if native:
        print("  2. Type of App: Native App (public client — local PKCE)", flush=True)
        print(
            "     After saving, copy the NEW Client ID from Keys and tokens into .env",
            flush=True,
        )
    else:
        print("  2. Type of App: Web App (confidential — has Client Secret)", flush=True)
    print(f"  3. Callback URI (exact): {env['X_REDIRECT_URI']}", flush=True)
    print(f"  4. Website URL: {env['X_REDIRECT_URI'].rsplit('/', 1)[0]}", flush=True)
    print("  5. App permissions: Read", flush=True)
    print(f"  6. Scopes requested: {' '.join(scopes)}", flush=True)
    print("  7. Save settings, wait ~2 min, then retry", flush=True)
    if "127.0.0.1" in env["X_REDIRECT_URI"] or "localhost" in env["X_REDIRECT_URI"]:
        print(
            "  Tip: if authorize still fails, use a custom hostname instead of localhost:\n"
            "    sudo sh -c 'echo \"127.0.0.1 xoauth.local\" >> /etc/hosts'\n"
            "    X_REDIRECT_URI=http://xoauth.local:8765/callback  (portal must match)",
            flush=True,
        )


def build_authorize_session(
    env: dict[str, str], scopes: list[str] | None = None
) -> tuple[str, str, str]:
    scopes = scopes or SCOPES
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": env["X_CLIENT_ID"],
        "redirect_uri": env["X_REDIRECT_URI"],
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return authorize_url, verifier, state


def save_pending(verifier: str, state: str, scopes: list[str]) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(
        json.dumps(
            {"code_verifier": verifier, "state": state, "scopes": scopes},
            indent=2,
        ),
        encoding="utf-8",
    )
    PENDING_PATH.chmod(0o600)


def load_pending() -> dict[str, str]:
    if not PENDING_PATH.exists():
        raise RuntimeError(
            f"No pending OAuth session at {PENDING_PATH}. Run: uv run x-fetch login --url-only"
        )
    return cast("dict[str, str]", json.loads(PENDING_PATH.read_text(encoding="utf-8")))


def clear_pending() -> None:
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()


def exchange_authorization_code(env: dict[str, str], code: str, verifier: str) -> None:
    headers = token_request_headers(env)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": env["X_REDIRECT_URI"],
        "code_verifier": verifier,
        "client_id": env["X_CLIENT_ID"],
    }
    token_response = post_form(TOKEN_URL, data, headers)
    save_tokens(token_response)
    clear_pending()
    print(f"Saved tokens to {TOKEN_PATH}", flush=True)
    print("Next: uv run x-fetch fetch --likes --bookmarks --months 12", flush=True)


def cmd_login_url_only(env: dict[str, str], *, minimal: bool = False) -> None:
    scopes = login_scopes(minimal)
    authorize_url, verifier, state = build_authorize_session(env, scopes)
    save_pending(verifier, state, scopes)
    if minimal:
        print(
            "Using minimal scopes (OAuth test only — re-login without --minimal "
            "for likes/bookmarks).",
            flush=True,
        )
    warn_if_custom_host_unresolved(env["X_REDIRECT_URI"])
    print_portal_checklist(env, scopes)
    print("\nStep 1: open this URL and authorize the app:", flush=True)
    print(f"\n{authorize_url}\n", flush=True)
    webbrowser.open(authorize_url)
    print(
        "Step 2: after authorizing, copy the FULL redirect URL from your browser "
        "(even if the page fails to load), then run:\n"
        "  uv run x-fetch login --callback '<paste URL here>'",
        flush=True,
    )


def cmd_login_callback(env: dict[str, str], callback: str) -> None:
    parsed = urllib.parse.urlparse(callback.strip())
    qs = urllib.parse.parse_qs(parsed.query)
    if "error" in qs:
        raise RuntimeError(f"Authorization failed: {qs['error'][0]}")
    code = qs.get("code", [""])[0]
    if not code:
        raise RuntimeError("Callback URL missing ?code= parameter.")
    pending = load_pending()
    returned_state = qs.get("state", [""])[0]
    if returned_state != pending.get("state"):
        raise RuntimeError("State mismatch — use the URL from the same login --url-only session.")
    verifier = pending.get("code_verifier", "")
    if not verifier:
        raise RuntimeError("Pending session missing code_verifier; run login --url-only again.")
    exchange_authorization_code(env, code, verifier)


def port_holder_pids(port: int) -> list[str]:
    """Return PIDs listening on the given TCP port via lsof (best-effort)."""
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    try:
        result = subprocess.run(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [pid for pid in result.stdout.split() if pid.strip()]


def port_in_use_message(port: int) -> str:
    """Build an actionable error message for a busy OAuth callback port."""
    pids = port_holder_pids(port)
    if pids:
        free_it = f"  kill {' '.join(pids)}\n"
    else:
        free_it = f"  lsof -nP -iTCP:{port} -sTCP:LISTEN   # find the PID, then: kill <PID>\n"
    return (
        f"Port {port} is already in use — most likely a previous, interrupted "
        "`login` run is still holding the OAuth callback socket.\n"
        f"Free it and retry:\n{free_it}"
        "Or skip the local server with the two-step flow:\n"
        "  uv run x-fetch login --url-only\n"
        "  uv run x-fetch login --callback '<redirect-url>'"
    )


def cmd_login(env: dict[str, str], *, minimal: bool = False) -> None:
    scopes = login_scopes(minimal)
    authorize_url, verifier, state = build_authorize_session(env, scopes)
    save_pending(verifier, state, scopes)
    if minimal:
        print("Using minimal scopes (OAuth test only).", flush=True)
    print_portal_checklist(env, scopes)

    captured: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != urllib.parse.urlparse(env["X_REDIRECT_URI"]).path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("state", [""])[0] != state:
                self.send_error(400, "State mismatch")
                return
            if "error" in qs:
                captured["error"] = qs["error"][0]
            else:
                captured["code"] = qs.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>X authorization complete</h1>"
                b"<p>You can close this tab and return to the terminal.</p></body></html>"
            )

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    redirect = urllib.parse.urlparse(env["X_REDIRECT_URI"])
    port = redirect.port or (443 if redirect.scheme == "https" else 80)
    bind_host = callback_bind_host(env["X_REDIRECT_URI"])
    warn_if_custom_host_unresolved(env["X_REDIRECT_URI"])
    try:
        server = HTTPServer((bind_host, port), CallbackHandler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        raise SystemExit(port_in_use_message(port)) from exc

    print("Opening browser for X authorization...", flush=True)
    print(f"If it does not open, visit:\n{authorize_url}\n", flush=True)
    webbrowser.open(authorize_url)
    print(f"Waiting for callback on {env['X_REDIRECT_URI']} ...", flush=True)
    server.handle_request()

    if captured.get("error"):
        raise RuntimeError(f"Authorization failed: {captured['error']}")
    code = captured.get("code")
    if not code:
        raise RuntimeError("No authorization code received.")
    exchange_authorization_code(env, code, verifier)


def users_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    users = payload.get("includes", {}).get("users", [])
    return {u["id"]: u for u in users}


def tweet_to_record(tweet: dict[str, Any], users: dict[str, dict[str, Any]]) -> dict[str, Any]:
    author = users.get(tweet.get("author_id", ""), {})
    handle = author.get("username", "i")
    metrics = tweet.get("public_metrics") or {}
    return {
        "id": tweet["id"],
        "text": tweet_text(tweet),
        "created_at": tweet.get("created_at"),
        "author_name": author.get("name", "unknown"),
        "author_handle": handle,
        "url": f"https://x.com/{handle}/status/{tweet['id']}",
        "metrics": {
            "likes": metrics.get("like_count", 0),
            "retweets": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
        },
        "_raw": tweet,
    }


def paginate_tweets(
    access_token: str,
    path: str,
    *,
    months: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Paginate likes/bookmarks; return tweet records and merged media index."""
    results: list[dict[str, Any]] = []
    all_media: dict[str, dict[str, Any]] = {}
    pagination_token: str | None = None
    pages = 0
    stop = False

    while pages < max_pages and not stop:
        params = {
            "max_results": "100",
            "tweet.fields": TWEET_FIELDS,
            "expansions": EXPANSIONS,
            "user.fields": USER_FIELDS,
            "media.fields": MEDIA_FIELDS,
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        payload = api_get(path, access_token, params)
        users = users_index(payload)
        all_media.update(media_index(payload))
        tweets = payload.get("data") or []
        if not tweets:
            break

        for tweet in tweets:
            created = parse_iso_date(tweet.get("created_at"))
            if months and created and not within_months(created, months):
                stop = True
                continue
            results.append(tweet_to_record(tweet, users))

        pagination_token = (payload.get("meta") or {}).get("next_token")
        pages += 1
        if not pagination_token:
            break

    return results, all_media


def write_tweets(
    tweets: list[dict[str, Any]],
    dest: Path,
    *,
    source_type: str,
    dry_run: bool,
    date_field: str,
    media_by_key: dict[str, dict[str, Any]],
) -> tuple[int, int, int]:
    created = skipped = assets_downloaded = 0
    now = datetime.now(UTC).isoformat()
    for t in tweets:
        raw = t.get("_raw") or {}
        assets = process_tweet_assets(raw, media_by_key, dry_run=dry_run)
        if (
            assets.get("media")
            or assets.get("videos")
            or assets.get("articles")
            or assets.get("transcripts")
        ):
            assets_downloaded += 1
        preview = (t.get("text") or t["id"])[:80]
        out = dest / tweet_filename(t["id"], t["author_name"], preview)
        body = render_source_md(
            source_type=source_type,
            tweet_id=t["id"],
            author=t["author_name"],
            author_handle=t["author_handle"],
            tweet_url=t["url"],
            text=t.get("text", ""),
            liked_at=t.get("created_at") if date_field == "liked_at" else None,
            bookmarked_at=t.get("created_at") if date_field == "bookmarked_at" else None,
            saved_at=now,
            metrics=t.get("metrics"),
            assets=assets,
        )
        if write_if_missing(out, body, dry_run):
            created += 1
        else:
            skipped += 1
    return created, skipped, assets_downloaded


def cmd_fetch(env: dict[str, str], args: argparse.Namespace) -> None:
    if not args.likes and not args.bookmarks:
        print("Specify --likes and/or --bookmarks", file=sys.stderr)
        sys.exit(2)

    tokens = load_tokens()
    access_token = tokens.get("access_token")
    if not access_token:
        sys.exit(2)

    try:
        me = api_get("/users/me", access_token, {"user.fields": "username"})
    except RuntimeError:
        print("Access token expired; refreshing...")
        tokens = refresh_access_token(env, tokens)
        access_token = tokens["access_token"]
        me = api_get("/users/me", access_token, {"user.fields": "username"})

    user_id = me["data"]["id"]
    username = me["data"].get("username", "?")
    print(f"Authenticated as @{username} (id {user_id})")

    total_created = total_skipped = 0

    total_assets = 0

    if args.likes:
        print(f"Fetching likes (filter: tweet created within last {args.months} months)...")
        likes, likes_media = paginate_tweets(
            access_token,
            f"/users/{user_id}/liked_tweets",
            months=args.months,
            max_pages=args.max_pages,
        )
        print(f"  {len(likes)} tweet(s) matched; downloading media, articles, transcripts...")
        c, s, a = write_tweets(
            likes,
            RAW_LIKES,
            source_type="x-like-api",
            dry_run=args.dry_run,
            date_field="liked_at",
            media_by_key=likes_media,
        )
        print(f"Likes: {c} created, {s} skipped, {a} with assets")
        total_created += c
        total_skipped += s
        total_assets += a

    if args.bookmarks:
        print(f"Fetching bookmarks (filter: tweet created within last {args.months} months)...")
        bookmarks, bookmarks_media = paginate_tweets(
            access_token,
            f"/users/{user_id}/bookmarks",
            months=args.months,
            max_pages=args.max_pages,
        )
        print(f"  {len(bookmarks)} tweet(s) matched; downloading media, articles, transcripts...")
        c, s, a = write_tweets(
            bookmarks,
            RAW_BOOKMARKS,
            source_type="x-bookmark-api",
            dry_run=args.dry_run,
            date_field="bookmarked_at",
            media_by_key=bookmarks_media,
        )
        print(f"Bookmarks: {c} created, {s} skipped, {a} with assets")
        total_created += c
        total_skipped += s
        total_assets += a

    action = "Would write" if args.dry_run else "Wrote"
    print(
        f"\n{action} {total_created} file(s) under raw/x/ "
        f"({total_skipped} already present, {total_assets} with attachments)"
    )
    if total_created:
        print("Next: ask your agent to ingest new sources from raw/x/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="X API OAuth login and fetch for raw/x/")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Run OAuth 2.0 PKCE login and save tokens")
    login.add_argument(
        "--url-only",
        action="store_true",
        help="Print authorize URL and exit (use with --callback after browser auth)",
    )
    login.add_argument(
        "--callback",
        metavar="URL",
        help="Complete login using the redirect URL from the browser address bar",
    )
    login.add_argument(
        "--minimal",
        action="store_true",
        help="Request only tweet.read users.read offline.access (debug portal issues)",
    )

    fetch = sub.add_parser("fetch", help="Fetch likes/bookmarks into raw/x/")
    fetch.add_argument("--likes", action="store_true", help="Fetch liked tweets")
    fetch.add_argument("--bookmarks", action="store_true", help="Fetch bookmarks")
    fetch.add_argument(
        "--months", type=int, default=12, help="Stop when tweets are older than N months"
    )
    fetch.add_argument(
        "--max-pages", type=int, default=50, help="Safety cap on API pages (100 items/page)"
    )
    fetch.add_argument("--dry-run", action="store_true", help="Report without writing files")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    env = require_env()

    if args.command == "login":
        if args.callback:
            cmd_login_callback(env, args.callback)
        elif args.url_only:
            cmd_login_url_only(env, minimal=args.minimal)
        else:
            cmd_login(env, minimal=args.minimal)
        return 0
    if args.command == "fetch":
        cmd_fetch(env, args)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
