---
description: Show the ingest worklist — sources that are new, pending, changed, or missing.
argument-hint: "[domain]"
---

# Pending ingest worklist

Show what is waiting to be folded into the wiki. Run the worklist engine read-only:

```bash
uv run wiki-plan
```

Domain filter: $ARGUMENTS

If a domain is given above, pass it as `uv run wiki-plan --domain $ARGUMENTS`. Summarize the `new` / `pending` / `changed` / `missing` buckets and stop — do not ingest anything or modify the manifest.
