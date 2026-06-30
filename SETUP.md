# Setup

This guide takes a fresh clone to a working LLM Wiki: the engine installed, an external vault seeded, the search index built, and the retrieval server registered with your assistant.

The engine is mandatory regardless of how you drive it. The skills and the MCP server resolve your vault from `WIKI_VAULT`, so even the Copilot plugin install still needs the steps below.

## Requirements

| Tool | Why | Notes |
|------|-----|-------|
| [uv](https://docs.astral.sh/uv/) | Python toolchain that runs every console script | `bin/setup.sh` installs it for you on consent |
| Python 3.12+ | Engine runtime | `uv` installs a managed build if yours is older |
| A vault folder | Holds the wiki and raw sources | An [Obsidian](https://obsidian.md/) vault is ideal; any directory works |
| git | Vault history (optional) | Only needed if you track the vault in git |

## Quickest path: clone and run setup

```bash
git clone https://github.com/erikschlegel/jarvis-vault.git
cd jarvis-vault
bash bin/setup.sh
```

The script is idempotent and safe to re-run. It detects what is already in place, asks before installing anything, and walks you through the rest:

1. Detects uv, Python, git, and whether a vault is already configured.
2. Installs uv and a Python 3.12 build only with your confirmation.
3. Runs `uv sync` to install the engine and its console scripts.
4. Prompts for where the vault should live (default `~/obsidian/jarvis-vault`), creates `wiki/` and `raw/` siblings, and writes `WIKI_VAULT` to `.env`.
5. Seeds the vault from the shipped template and builds the search index (`wiki-init`).
6. Registers the `jarvis-vault` MCP server with VS Code; with the GitHub Copilot CLI when it is installed, or by writing `~/.copilot/mcp-config.json` directly when it is not.
7. Verifies the result with `wiki-doctor`.

Useful flags:

| Flag | Effect |
|------|--------|
| `--check` | Report status read-only and make no changes |
| `--yes` | Assume yes for every prompt (non-interactive) |
| `--no-build` | Skip the search-index build (offline-friendly) |
| `--vault-parent <dir>` | Directory that will contain the vault folder |
| `--vault-name <name>` | Vault folder name (default `jarvis-vault`) |

A non-interactive bootstrap looks like:

```bash
bash bin/setup.sh --yes --vault-parent ~/obsidian --vault-name research
```

## Manual path

If you would rather run each step yourself:

1. Install dependencies from the repo root:

   ```bash
   uv sync
   ```

2. Point the engine at your vault. Copy the example env file and set `WIKI_VAULT` to the absolute path of the vault's wiki root (the folder that will hold `index.md`):

   ```bash
   cp .env.example .env
   # then edit .env: WIKI_VAULT=/absolute/path/to/your-vault/wiki
   ```

   The `.env` is discovered automatically from the working directory upward, then this repo, then `~/.config/jarvis-vault/.env`. A real exported environment variable always wins over the file.

3. Seed the vault and build the index:

   ```bash
   uv run wiki-init
   ```

   Re-running is safe: it never overwrites existing pages. Pass `--force` to re-copy the template or `--no-build` to skip the index build when offline.

4. The seed template places its `.obsidian/` config inside the wiki folder. The graph view is tuned to `path:wiki/` (so `raw/` stays out of the graph) and color-codes `entities`, `concepts`, `sources`, and `comparisons`; the shipped `.obsidian/workspace.json` also opens a fresh vault straight into the Graph view, with file-explorer/search/bookmarks docked left and backlinks/outgoing-links/tags/properties/outline collapsed right (first launch only — Obsidian rewrites `workspace.json` thereafter, which is why the live copy is gitignored). Move that config up to the vault root once so it applies:

   ```bash
   mv /path/to/your-vault/wiki/.obsidian /path/to/your-vault/.obsidian
   ```

   `bin/setup.sh` does this for you.

5. Confirm everything read-only:

   ```bash
   uv run wiki-doctor
   ```

## Register the retrieval server

The `jarvis-vault` MCP server (`wiki-mcp`) exposes the wiki to assistants that speak the Model Context Protocol. `wiki-init` prints both client forms; here is what each needs.

### GitHub Copilot CLI and desktop

The Copilot CLI auto-starts MCP servers listed in `~/.copilot/mcp-config.json`. Register the server once and it starts on every launch:

```bash
copilot mcp add jarvis-vault -- uv run --directory /path/to/jarvis-vault wiki-mcp
```

The engine reads `WIKI_VAULT` from your `.env`, so no secret lives in the client config. To wire it by hand, add this block to `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "jarvis-vault": {
      "type": "local",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/jarvis-vault", "wiki-mcp"],
      "env": { "WIKI_VAULT": "/path/to/your-vault/wiki" },
      "tools": ["*"]
    }
  }
}
```

Manage the registration with `copilot mcp list`, `copilot mcp get jarvis-vault`, and `copilot mcp remove jarvis-vault`.

### VS Code

This repo ships [.vscode/mcp.json](.vscode/mcp.json), so VS Code picks up the `jarvis-vault` server automatically after you trust it once. It reads `WIKI_VAULT` from your `.env`, no prompt. For another client, paste the portable snippet `wiki-init` printed (the `uv run --directory <repo>` form).

## Install the skills as a Copilot plugin

The skills are packaged as GitHub Copilot plugins through the marketplace at [.github/plugin/marketplace.json](.github/plugin/marketplace.json). Register the marketplace and install the plugins from your terminal:

```bash
copilot plugin marketplace add erikschlegel/jarvis-vault
copilot plugin install wiki-core@jarvis-vault
copilot plugin install wiki-connector-x@jarvis-vault
```

From a local clone, point the marketplace command at the checkout instead: `copilot plugin marketplace add /path/to/jarvis-vault`. To skip the marketplace entirely, install a plugin straight from its subdirectory:

```bash
copilot plugin install erikschlegel/jarvis-vault:plugins/wiki-core
```

The interactive-session equivalents are `/plugin marketplace add` and `/plugin install`. You can also enable plugins declaratively through the `enabledPlugins` map (a `{ "spec": true }` object, not an array) in `~/.copilot/settings.json` (all projects) or `.github/copilot/settings.json` (this repo). When the `copilot` binary is absent, `bin/setup.sh` does this for you: it writes local-path specs (`<repo>/plugins/wiki-core` and `<repo>/plugins/wiki-connector-x`) into `enabledPlugins`, so a desktop-only user gets the skills wired without the CLI. Restart the Copilot desktop app afterward to load them.

The plugin delivers only the skills. The engine still resolves your vault from `WIKI_VAULT`, so run `bin/setup.sh` or the manual steps above, then verify with `uv run wiki-doctor`.

## Troubleshooting

`wiki-doctor` is the single source of truth for setup health. Run `uv run wiki-doctor` (or `bash bin/setup.sh --check`) and match the failing check below.

| Check | Meaning | Fix |
|-------|---------|-----|
| `python` | Interpreter older than 3.12 | `uv python install 3.12`, then re-run setup |
| `WIKI_VAULT` | Not set or unresolvable | Set `WIKI_VAULT` in `.env` (copy `.env.example`) |
| `vault directory` | Path missing on disk | `uv run wiki-init` to create and seed it |
| `index.md` | Vault not seeded | `uv run wiki-init` |
| `search index` | Index not built | `uv run wiki-init` or `uv run wiki-search build` |
| `console scripts` | Engine not installed | `uv sync` |
| `mcp registration` | Server not registered | Re-run `bin/setup.sh` or follow the steps above |

For the X (Twitter) connector — API credentials, fetching likes and bookmarks, local video transcription — continue with the [wiki-connector-x setup](plugins/wiki-connector-x/README.md#setup).
