#!/usr/bin/env python3
"""Source-adapter seam that decouples the wiki engine from any one content type.

The ingest planner and the scaffolder used to hardwire X (Twitter) parsing: how
to derive an identity, strip render boilerplate, build a canonical URL, and flag
attached video. That coupling meant every new content type (web clips, PDFs,
notes) would have to be bolted onto the core.

This module inverts the dependency. The core owns a small ``SourceAdapter``
contract and a generic ``DefaultAdapter``; connectors register their own adapters
through the ``wiki_core.source_adapters`` entry-point group. The core never imports
a connector — it discovers adapters at runtime and dispatches per raw file.

Two identity keys ride on every source, both connector-agnostic:
  - ``source_id``: the stable identity value (per-adapter: an X status id, a URL
    hash, a content hash) under one uniform key.
  - ``source_type``: the discriminator naming the adapter kind (``x``, ``web``,
    ``doc``) — distinct from the OKF page-kind ``type: source``.
"""

from __future__ import annotations

import functools
import importlib.metadata
import logging
import re
from pathlib import Path

from wiki_core import paths

logger = logging.getLogger(__name__)

# Entry-point group connectors register their adapter classes under. Core scans
# this group at runtime; it never imports a connector package directly.
ENTRY_POINT_GROUP = "wiki_core.source_adapters"


class SourceAdapter:
    """Contract for turning a raw source file into planner/scaffolder inputs.

    Subclass and override for a specific content type. The base implementation is
    already a working generic adapter (see ``DefaultAdapter``); connectors only
    override the pieces that differ (identity derivation, body cleaning, URL
    construction, asset flags, and the extra frontmatter/notices they emit).
    """

    #: Connector kind written to each source page's ``source_type`` frontmatter.
    source_type: str = "doc"

    #: Raw subdirectories (immediately under ``raw/``) this adapter claims.
    owned_subdirs: tuple[str, ...] = ()

    def source_type_for(self, fm: dict[str, str]) -> str:
        """The ``source_type`` value for a given source; defaults to the class kind."""
        return self.source_type

    def owns(self, path: Path, fm: dict[str, str]) -> bool:
        """True when this adapter is responsible for ``path``/``fm``.

        The base check claims files under any of ``owned_subdirs``. Adapters can
        widen this (e.g. recognise a source by a frontmatter field regardless of
        location) by overriding and calling ``super().owns(...)``.
        """
        try:
            rel = path.relative_to(paths.raw_root())
        except ValueError:
            return False
        return bool(rel.parts) and rel.parts[0] in self.owned_subdirs

    def source_id(self, fm: dict[str, str], path: Path) -> str:
        """Stable identity for a source: explicit ``source_id`` field, else filename stem."""
        return fm.get("source_id") or path.stem

    def clean_body(self, fm: dict[str, str], body: str) -> str:
        """Recover the substantive text used for slugs and change hashing.

        The generic cleaner drops blank lines, horizontal rules, and the
        ``## Attachments`` trailer, then collapses whitespace. Connectors override
        to strip render-format boilerplate specific to their source.
        """
        lines: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "---":
                continue
            if stripped.startswith("## Attachments"):
                break
            lines.append(stripped)
        return re.sub(r"\s+", " ", " ".join(lines)).strip()

    def resource_url(self, fm: dict[str, str], source_id: str) -> str:
        """The canonical URL for the source; empty when none is known."""
        return fm.get("resource") or fm.get("url") or ""

    def author_handle(self, fm: dict[str, str]) -> str:
        """A handle used for author-based domain scoring; empty when not applicable."""
        return fm.get("author_handle", "")

    def source_label(self, fm: dict[str, str]) -> str:
        """The human label for the page's ``**Source:**`` line."""
        return fm.get("author") or "source"

    def asset_flags(self, fm: dict[str, str], raw_text: str) -> dict[str, bool]:
        """Attachment flags recorded on the plan record and manifest entry."""
        return {"has_video": False, "video_transcribed": False}

    def scaffold_frontmatter(
        self, record: dict[str, object], fm: dict[str, str], raw_text: str
    ) -> list[str]:
        """Extra frontmatter lines to append after the generic OKF keys."""
        return []

    def scaffold_notices(
        self, record: dict[str, object], fm: dict[str, str], raw_text: str
    ) -> list[str]:
        """Extra body admonition lines inserted after the ``**Source:**`` line."""
        return []


class DefaultAdapter(SourceAdapter):
    """Generic adapter for connector-agnostic raw files (the ``raw/inbox`` drop)."""

    source_type = "doc"
    owned_subdirs = ("inbox",)

    def source_type_for(self, fm: dict[str, str]) -> str:
        """Honour an explicit ``source_type`` in the raw frontmatter (e.g. ``web``)."""
        return fm.get("source_type") or self.source_type

    def resource_url(self, fm: dict[str, str], source_id: str) -> str:
        return fm.get("resource") or fm.get("url") or ""


@functools.cache
def _registered() -> tuple[SourceAdapter, ...]:
    """Instantiate every adapter registered under ``ENTRY_POINT_GROUP`` (cached)."""
    found: list[SourceAdapter] = []
    for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            adapter_cls = entry.load()
            found.append(adapter_cls())
        except Exception as exc:  # pragma: no cover - defensive against bad plugins
            logger.warning("source adapter %r failed to load: %s", entry.name, exc)
    return tuple(found)


def registered_adapters() -> tuple[SourceAdapter, ...]:
    """The discovered connector adapters (excludes the always-available default)."""
    return _registered()


def clear_cache() -> None:
    """Drop the cached adapter registry (used by tests that register adapters)."""
    _registered.cache_clear()


def adapter_for(path: Path, fm: dict[str, str]) -> SourceAdapter:
    """The first registered adapter that ``owns`` the source, else ``DefaultAdapter``."""
    for adapter in _registered():
        try:
            if adapter.owns(path, fm):
                return adapter
        except Exception as exc:  # pragma: no cover - defensive against bad plugins
            logger.warning("source adapter %r owns() failed: %s", type(adapter).__name__, exc)
    return DefaultAdapter()


def adapter_by_type(source_type: str) -> SourceAdapter:
    """The registered adapter whose ``source_type`` matches, else ``DefaultAdapter``."""
    for adapter in _registered():
        if adapter.source_type == source_type:
            return adapter
    return DefaultAdapter()
