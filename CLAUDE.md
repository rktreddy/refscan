# refscan — working conventions

CLI tool for reference-PDF collection and paper-vs-references plagiarism scanning.
This file is the authoritative guidance for working in this repo; the larger
`CLAUDE.md` files in parent directories are about a separate paper-writing
system and do not apply here.

## Toolchain
- **uv** is the workflow. Test: `uv run --extra dev pytest`. Lint:
  `uv run --extra dev ruff check .`.
- **ruff** is the only lint gate (config in `pyproject.toml`). Ignore the IDE's
  pylint warnings — pylint is not used here.
- The `.venv` is uv-created. `pip` was added back so `python -m pip` works for
  IDE tooling; don't rely on it for installs — use `uv pip`.

## Code constraints
- **stdlib-only at runtime** (`pyproject` has no runtime deps). Test/lint deps
  go in the `dev` optional-dependency group only. Runtime system dep:
  `pdftotext` (poppler).
- Targets **Python 3.10+**. So per-paper config is **JSON, not TOML** — there is
  no `tomllib` on 3.10. Don't reintroduce a TOML dependency.
- `bib.parse_bib` is a deliberately minimal parser (plain BibTeX, one level of
  brace nesting). Keep it minimal; don't pull in a BibLaTeX library.
- Categorization heuristics are per-paper, loaded from an optional
  `<paper_dir>/refscan.json` (`track.py`) — never hardcode paper-specific
  titles/keys in the package.

## Releasing
1. Add a `## [X.Y.Z]` section to `CHANGELOG.md`.
2. `refscan release X.Y.Z` (bumps `pyproject.toml` + `__init__.py`, runs tests,
   commits, tags `vX.Y.Z`). Requires an editable install and a clean tree on
   `main`. Add `--push` to publish, or push manually.

## Git
- Stage files **explicitly**; do not `git add -A` (the repo sits next to
  untracked local docs).
- `refscan_roadmap.md` is a gitignored, maintainer-only planning doc — keep it
  current locally, but never commit it.
- CI (`.github/workflows/ci.yml`) runs ruff + a pytest matrix (3.10–3.13) on
  push/PR to `main`. Keep it green.
