#!/usr/bin/env python3
"""OAuth login and fetch likes/bookmarks from the X API into raw/x/.

Setup (one time):
  1. Copy .env.example → .env and fill X_CLIENT_ID / X_CLIENT_SECRET
  2. In the X developer portal, set callback URL to X_REDIRECT_URI (default below)
  3. App permissions: Read; enable OAuth 2.0; scopes: tweet.read users.read like.read bookmark.read offline.access
  4. Run: python3 scripts/fetch_x_api.py login

Fetch:
  python3 scripts/fetch_x_api.py fetch --likes --bookmarks --months 12

Do not commit .env or .secrets/.
"""
from __future__ import annotations

import argparse
import sys
import base64
import hashlib
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from x_source_io import (
    RAW_BOOKMARKS,
    RAW_LIKES,
    REPO_ROOT,
    parse_iso_date,
    render_source_md,
    tweet_filename,
    within_months,
    write_if_missing,
)

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

ENV_PATH = REPO_ROOT / ".env"
SECRETS_DIR = REPO_ROOT / ".secrets"
TOKEN_PATH = SECRETS_DIR / "x_tokens.json"

TWEET_FIELDS = "created_at,public_metrics,author_id,text"
USER_FIELDS = "username,name"
EXPANSIONS = "author_id"


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


def require_env() -> dict[str, str]:
    env = load_env(ENV_PATH)
    missing = [k for k in ("X_CLIENT_ID", "X_CLIENT_SECRET") if not env.get(k)]
    if missing:
        print(
            f"Missing in {ENV_PATH}: {', '.join(missing)}\n"
            "Copy .env.example to .env and add values from the X developer portal.",
            file=sys.stderr,
        )
        sys.exit(2)
    env.setdefault("X_REDIRECT_URI", "http://127.0.0.1:8765/callback")
    return env


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{urllib.parse.quote(client_id)}:{urllib.parse.quote(client_secret)}"
    return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")


def post_form(url: str, data: dict[str, str], headers: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def api_get(path: str, access_token: str, params: dict[str, str] | None = None) -> dict:
    query = urllib.parse.urlencode(params or {})
    url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {path}: {detail}") from exc


def save_tokens(payload: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)


def load_tokens() -> dict:
    if not TOKEN_PATH.exists():
        print(
            f"No tokens at {TOKEN_PATH}. Run: python3 scripts/fetch_x_api.py login",
            file=sys.stderr,
        )
        sys.exit(2)
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def refresh_access_token(env: dict[str, str], tokens: dict) -> dict:
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("No refresh_token; run login again.")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": basic_auth_header(env["X_CLIENT_ID"], env["X_CLIENT_SECRET"]),
    }
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
    token = tokens.get("access_token")
    if not token:
        raise RuntimeError("Token file missing access_token; run login again.")
    return token


def cmd_login(env: dict[str, str]) -> None:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": env["X_CLIENT_ID"],
        "redirect_uri": env["X_REDIRECT_URI"],
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

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

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    redirect = urllib.parse.urlparse(env["X_REDIRECT_URI"])
    port = redirect.port or (443 if redirect.scheme == "https" else 80)
    server = HTTPServer((redirect.hostname or "127.0.0.1", port), CallbackHandler)

    print("Opening browser for X authorization...")
    print(f"If it does not open, visit:\n{authorize_url}\n")
    webbrowser.open(authorize_url)
    print(f"Waiting for callback on {env['X_REDIRECT_URI']} ...")
    server.handle_request()

    if captured.get("error"):
        raise RuntimeError(f"Authorization failed: {captured['error']}")
    code = captured.get("code")
    if not code:
        raise RuntimeError("No authorization code received.")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": basic_auth_header(env["X_CLIENT_ID"], env["X_CLIENT_SECRET"]),
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": env["X_REDIRECT_URI"],
        "code_verifier": verifier,
        "client_id": env["X_CLIENT_ID"],
    }
    token_response = post_form(TOKEN_URL, data, headers)
    save_tokens(token_response)
    print(f"Saved tokens to {TOKEN_PATH}")
    print("Next: python3 scripts/fetch_x_api.py fetch --likes --bookmarks --months 12")


def users_index(payload: dict) -> dict[str, dict]:
    users = payload.get("includes", {}).get("users", [])
    return {u["id"]: u for u in users}


def tweet_to_record(tweet: dict, users: dict[str, dict]) -> dict:
    author = users.get(tweet.get("author_id", ""), {})
    handle = author.get("username", "i")
    metrics = tweet.get("public_metrics") or {}
    return {
        "id": tweet["id"],
        "text": tweet.get("text", ""),
        "created_at": tweet.get("created_at"),
        "author_name": author.get("name", "unknown"),
        "author_handle": handle,
        "url": f"https://x.com/{handle}/status/{tweet['id']}",
        "metrics": {
            "likes": metrics.get("like_count", 0),
            "retweets": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
        },
    }


def paginate_tweets(
    access_token: str,
    path: str,
    *,
    months: int,
    max_pages: int,
) -> list[dict]:
    """Paginate an X API timeline endpoint that returns tweet objects."""
    results: list[dict] = []
    pagination_token: str | None = None
    pages = 0
    stop = False

    while pages < max_pages and not stop:
        params = {
            "max_results": "100",
            "tweet.fields": TWEET_FIELDS,
            "expansions": EXPANSIONS,
            "user.fields": USER_FIELDS,
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        payload = api_get(path, access_token, params)
        users = users_index(payload)
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

    return results


def write_tweets(
    tweets: list[dict],
    dest: Path,
    *,
    source_type: str,
    dry_run: bool,
    date_field: str,
) -> tuple[int, int]:
    created = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    for t in tweets:
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
        )
        if write_if_missing(out, body, dry_run):
            created += 1
        else:
            skipped += 1
    return created, skipped


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

    if args.likes:
        print(f"Fetching likes (filter: tweet created within last {args.months} months)...")
        likes = paginate_tweets(
            access_token,
            f"/users/{user_id}/liked_tweets",
            months=args.months,
            max_pages=args.max_pages,
        )
        c, s = write_tweets(
            likes,
            RAW_LIKES,
            source_type="x-like-api",
            dry_run=args.dry_run,
            date_field="liked_at",
        )
        print(f"Likes: {c} created, {s} skipped")
        total_created += c
        total_skipped += s

    if args.bookmarks:
        print(f"Fetching bookmarks (filter: tweet created within last {args.months} months)...")
        bookmarks = paginate_tweets(
            access_token,
            f"/users/{user_id}/bookmarks",
            months=args.months,
            max_pages=args.max_pages,
        )
        c, s = write_tweets(
            bookmarks,
            RAW_BOOKMARKS,
            source_type="x-bookmark-api",
            dry_run=args.dry_run,
            date_field="bookmarked_at",
        )
        print(f"Bookmarks: {c} created, {s} skipped")
        total_created += c
        total_skipped += s

    action = "Would write" if args.dry_run else "Wrote"
    print(f"\n{action} {total_created} file(s) under raw/x/ ({total_skipped} already present)")
    if total_created:
        print("Next: ask your agent to ingest new sources from raw/x/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="X API OAuth login and fetch for raw/x/")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Run OAuth 2.0 PKCE login and save tokens")

    fetch = sub.add_parser("fetch", help="Fetch likes/bookmarks into raw/x/")
    fetch.add_argument("--likes", action="store_true", help="Fetch liked tweets")
    fetch.add_argument("--bookmarks", action="store_true", help="Fetch bookmarks")
    fetch.add_argument("--months", type=int, default=12, help="Stop when tweets are older than N months")
    fetch.add_argument("--max-pages", type=int, default=50, help="Safety cap on API pages (100 items/page)")
    fetch.add_argument("--dry-run", action="store_true", help="Report without writing files")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    env = require_env()

    if args.command == "login":
        cmd_login(env)
        return 0
    if args.command == "fetch":
        cmd_fetch(env, args)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())