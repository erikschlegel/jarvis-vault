---
description: Fold a raw/ source into the wiki — the Ingest operation.
argument-hint: "[source | all]"
---

# Ingest a source

Run the **Ingest** operation per the wiki-ingest skill (`plugins/wiki-core/skills/wiki-ingest/SKILL.md`).

Source: $ARGUMENTS

- If a source is named above, ingest that one.
- If the argument is `all`, drain the pending worklist in bounded batches — cluster thin, related sources per the skill's **Batch mode** (get one go-ahead per cluster, ingest heavy or contradiction-bearing sources solo). Not a single monster call.
- With no argument, compute the worklist with `uv run wiki-plan`. If exactly one source is pending, ingest it. If several are pending, group them into batchable clusters and present that plan before folding any in.

The skill owns the write order, Batch mode, the `--mark-ingested` finalize step, and the `raw/` boundary.
