"""Portable filesystem locations for the LLM Wiki engine.

Every location resolves in the same order: the process environment, then a
discovered ``.env`` file, then a vault-relative default. ``WIKI_VAULT`` selects
the Obsidian vault root; the retrieval index, ingest state, and ingest config
all default to a ``.wiki_index/`` directory inside it. Each is independently
overridable so an installed consumer (``pip``/``uvx``) never depends on the
source-repo layout.

``WIKI_VAULT`` has no hardcoded fallback: the personal vault path lives in a
gitignored ``.env`` (see ``.env.example``), never in source. A real exported
environment variable always wins over the ``.env`` value.

``.env`` discovery is layered so it survives being installed away from the
source repo: the current working directory and its parents are searched first
(a consumer's project root), then this module's own directory tree (an editable
checkout), then the user config directory (``$XDG_CONFIG_HOME/erik-wiki`` or
``~/.config/erik-wiki``). The first ``.env`` found wins.

Environment variables:
  WIKI_VAULT       Obsidian vault wiki root (the directory holding index.md).
  WIKI_RAW         Immutable raw sources root (default ``<vault>/../raw``, the
                   sibling of the wiki inside the Obsidian vault).
  WIKI_INDEX_DIR   Retrieval index home (default ``<vault>/.wiki_index``; when
                   no vault is configured, a user cache fallback).
  WIKI_STATE       Ingest manifest path (default ``<index>/ingest_state.json``).
  WIKI_CONFIG      Ingest config path (default ``<index>/ingest_config.json``).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_DOTENV_NAME = ".env"


def _user_config_dir() -> Path:
    """User configuration directory for the engine (XDG, with a HOME fallback)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "erik-wiki"


def _user_cache_dir() -> Path:
    """User cache directory for derived, rebuildable state (XDG, HOME fallback)."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "erik-wiki"


def _candidate_dotenv_paths() -> list[Path]:
    """Ordered ``.env`` locations: CWD upward, this file upward, user config dir.

    Earlier entries win. The current working directory comes first so a
    consumer's project ``.env`` overrides one that happens to sit higher in the
    source checkout; the user config directory is the last resort.
    """
    seen: set[Path] = set()
    candidates: list[Path] = []

    def add(path: Path) -> None:
        if path not in seen:
            seen.add(path)
            candidates.append(path)

    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        add(parent / _DOTENV_NAME)
    here = Path(__file__).resolve()
    for parent in here.parents:
        add(parent / _DOTENV_NAME)
    add(_user_config_dir() / _DOTENV_NAME)
    return candidates


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str]:
    """Parse ``KEY=value`` pairs from the first discovered ``.env`` (best-effort)."""
    for path in _candidate_dotenv_paths():
        if path.is_file():
            return _parse_dotenv(path)
    return {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a single ``.env`` file into a ``KEY -> value`` mapping."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(name: str) -> str | None:
    """Resolve ``name`` from the process environment, then a discovered ``.env``."""
    return os.environ.get(name) or _dotenv().get(name)


def _env_path(name: str) -> Path | None:
    """Return an expanded ``Path`` from ``name`` (environment or ``.env``), if set."""
    raw = _env(name)
    return Path(raw).expanduser() if raw else None


def find_vault() -> Path | None:
    """Resolve the Obsidian vault wiki root, or ``None`` when unconfigured.

    Non-raising counterpart to ``default_vault()``: callers that must degrade
    gracefully when ``WIKI_VAULT`` is unset (the MCP server, ``wiki-doctor``)
    use this instead of triggering the ``SystemExit`` guidance.
    """
    return _env_path("WIKI_VAULT")


def default_vault() -> Path:
    """Resolve the Obsidian vault wiki root, or exit with setup guidance.

    Used by flows that genuinely require a configured vault (index build, raw
    source enumeration). Fail-soft callers should use ``find_vault()``.
    """
    vault = find_vault()
    if vault is None:
        raise SystemExit(
            "WIKI_VAULT is not set. Run `uv run wiki-init` after pointing WIKI_VAULT at "
            "your Obsidian vault wiki root -- the directory that holds index.md -- via .env "
            "(copy .env.example) or an exported environment variable."
        )
    return vault


def raw_root() -> Path:
    """Resolve the immutable raw sources root (``WIKI_RAW`` or ``<vault>/../raw``).

    Raw sources live as a sibling of the wiki inside the Obsidian vault, so the
    default anchors on ``default_vault().parent``. Stored manifest/frontmatter
    paths (``raw/x/...``) are relative to ``raw_root().parent``; readers and
    writers join against that anchor so the strings stay stable wherever raw
    physically lives.
    """
    return _env_path("WIKI_RAW") or (default_vault().parent / "raw")


def index_dir() -> Path:
    """Resolve the retrieval index home (non-raising).

    ``WIKI_INDEX_DIR`` wins; otherwise it is ``<vault>/.wiki_index`` when a vault
    is configured, or a user cache fallback when none is. The fallback keeps
    module-level path constants resolvable at import time even with ``WIKI_VAULT``
    unset, so the MCP server can start and report a friendly error per call
    instead of crashing on import.
    """
    explicit = _env_path("WIKI_INDEX_DIR")
    if explicit is not None:
        return explicit
    vault = find_vault()
    if vault is not None:
        return vault / ".wiki_index"
    return _user_cache_dir() / "index"


def state_path() -> Path:
    """Resolve the ingest manifest path (``WIKI_STATE`` or ``<index>/ingest_state.json``)."""
    return _env_path("WIKI_STATE") or (index_dir() / "ingest_state.json")


def config_path() -> Path:
    """Resolve the ingest config path (``WIKI_CONFIG`` or ``<index>/ingest_config.json``)."""
    return _env_path("WIKI_CONFIG") or (index_dir() / "ingest_config.json")
