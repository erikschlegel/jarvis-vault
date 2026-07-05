---
description: Onboard or repair the wiki engine — seed the vault, build the index, print the MCP entry.
---

# Set up the wiki

**Prerequisite:** the toolchain is already installed — `uv` and the synced environment, set up by `bin/setup.sh`. This command drives the engine; it does not install dev tooling (`uv`, Python, or dependencies). If `uv` is missing, stop and point the user at `bash bin/setup.sh`.

Get the vault to a working state across all three access tiers. Stop and report; do not ingest or modify sources.

1. Run `uv run wiki-init` to validate `WIKI_VAULT`, seed an empty vault from the shipped template, build the search index, and print an `mcp.json` server entry.
2. Run `uv run wiki-doctor` and report the configuration and index-health checks.
3. Surface any remaining steps — setting `WIKI_VAULT`, installing the skill plugins, or registering the `jarvis-vault` MCP server.
