---
description: Answer a question against the wiki, with citations — the Query operation.
argument-hint: "<question>"
---

# Query the wiki

Run the **Query** operation per the wiki-query skill (`plugins/wiki-core/skills/wiki-query/SKILL.md`).

Question: $ARGUMENTS

The skill owns retrieval-tier routing and citation discipline. Answer with citations to the wiki pages you used, and if the answer is durable, offer to file it back with `/save`.
