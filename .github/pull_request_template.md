## What & why


## Checklist
- [ ] Tests added/updated — `uv run --extra dev pytest` is green
- [ ] `uv run --extra dev ruff check .` passes
- [ ] `CHANGELOG.md` updated (for any user-visible change)
- [ ] Core stays **stdlib-only** at runtime (heavy deps go in an optional extra, lazy-loaded)
