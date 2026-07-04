# Obsidian Web Clipper — optional capture on-ramp

The [Obsidian Web Clipper](https://obsidian.md/clipper) browser extension is an **optional convenience** for capturing web pages into the wiki while you browse. It lands a markdown file in `raw/inbox/`, which the engine then folds in on the next [Ingest](../../AGENTS.md#ingest).

The clipper is the *human* capture path. The *canonical, programmatic* on-ramp is still `uv run wiki-add <url>` — it fetches, cleans the body more aggressively, and computes a content-derived `source_id`. Use the clipper when you are reading in the browser and want a one-click grab; use `wiki-add` from an agent or the terminal.

## What the template does

`web-clipper-template.json` writes a clip that is compatible with the `raw/inbox/` frontmatter, minus the identity field:

| Frontmatter | Value | Notes |
|-------------|-------|-------|
| `source_type` | `web` | Routes the file to the engine's generic `DefaultAdapter`. |
| `resource` | page URL | The canonical source URL. |
| `title` | page title | |
| `imported_at` | clip date (`YYYY-MM-DD`) | |

Elsewhere `raw/inbox/` files carry a uniform identity frontmatter that includes `source_id` (for example, `wiki-add` writes a content-derived id). The template deliberately omits `source_id`: the browser extension cannot compute a content hash. When the field is missing, `DefaultAdapter` derives `source_id` from the clip's filename stem at plan time (`wiki-plan`) — so a clean note name matters, and the template uses `{{title|safe_name}}` to produce a filesystem-safe stem. This filename-derived id differs from `wiki-add`'s content-derived one.

## Install and import

1. Install the **Obsidian Web Clipper** extension for your browser from <https://obsidian.md/clipper>.
2. Open the extension's **Settings → Templates**.
3. Choose **Import** and select [`web-clipper-template.json`](./web-clipper-template.json). This is a one-click import; the browser extension stores templates in its own storage, so it cannot be pre-configured from this repo.
4. Point the template's **vault** at the Obsidian vault that *contains* `raw/` — that is the parent of the wiki vault (`WIKI_VAULT`'s parent, e.g. `knowledge-map`), not the wiki vault itself. The template's note path is `raw/inbox`, so clips land in `raw/inbox/` beside the wiki.

## After clipping

Clipped files sit in `raw/inbox/` until you ingest them. Run `/pending` to see them on the worklist, then `/ingest` (or `/ingest all` to drain a backlog in bounded batches). A clipped file goes through the same `DefaultAdapter` and the same write protocol as a `wiki-add` file; the one difference is identity — its `source_id` comes from the filename stem rather than `wiki-add`'s content-derived hash, so keep that in mind when correlating raw files with plan and source ids.
