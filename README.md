# erik-knowledge-base

A git-backed personal knowledge base. Content lives as plain Markdown under `content/`.

## Structure

```text
content/
  index.md          # Home page and table of contents
  topics/           # Topical notes and reference material
  projects/         # Project-specific notes
  inbox/            # Quick captures to sort later
```

## Workflow

1. Add or edit Markdown files under `content/`.
2. Link related notes with relative paths, e.g. `[topic](topics/example.md)`.
3. Commit when a note is ready to keep.

```bash
git add content/
git commit -m "docs: add note on <topic>"
```

## Conventions

- Use lowercase kebab-case filenames (`my-topic.md`).
- Start each file with an `#` title.
- Prefer short, focused notes over long monolithic documents.