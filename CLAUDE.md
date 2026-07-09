# refscan — working conventions

CLI toolkit for research-paper reference integrity: PDF collection, plagiarism
scanning, reference verification (incl. fabricated/retracted detection), bib
hygiene, and auto-fix. This file is the authoritative guidance for working in
this repo; the larger `CLAUDE.md` files in parent directories are about a
separate paper-writing system and do not apply here.

## Commands (16 subcommands, dispatched in `cli.py`)
- `init` — scaffold `literature/` + a `refscan.json` template
- `fetch` — download cited PDFs (arXiv → S2 → OpenAlex → Unpaywall; TTY progress bar)
- `cite` — BibTeX entry from DOI/arXiv ID (Crossref→OpenAlex; `--add` appends, dedupe-aware)
- `doctor` — environment self-check (deps, backends, network, optional paper layout)
- `claims` — offline uncited-claim detector (advisory; always exits 0)
- `track` — categorize references → `reference_tracking.md`
- `scan` — exact shingle-match prose vs references (confidence-scored)
- `semscan` — semantic/near-duplicate scan (optional backends; paraphrase)
- `verify` — check entries vs arXiv/S2/OpenAlex/Crossref; flags fabricated + retracted + published-version-available (📰, advisory)
- `fix` — apply safe bib metadata corrections (DOIs, drifted years); `--upgrade-preprints` re-points preprint citations at the published version; preview unless `--apply`
- `sanity-stats` — bib hygiene (CI exit code)
- `refstats` — reference-balance stats (recency, self-citation)
- `check` — ⭐ one-shot sanity+scan(+verify) → PASS/WARN/FAIL; `--html/--json/--sarif`
- `watch` — re-scan on `.tex` save
- `overlap` — cross-paper self-plagiarism
- `release` — maintainer-only version bump/test/tag/push

`check` is the recommended entry point. All commands resolve inputs through
`layout.resolve_layout()` (CLI flag > `refscan.json` > auto-detect > default
`paper/{references.bib,sections}`).

## Module map (`src/refscan/`)
`cli` dispatcher · `bib` (parse + `ref_pdf_path` path-safety + `doi`) ·
`layout` (resolve/auto-detect) · `fetch` (sources + downloads) · `scan`
(shingles) · `semantic` (optional embeddings) · `verify` · `fix` · `sanity` ·
`track` (+ config) · `refstats` · `overlap` · `textproc` · `report`
(HTML/JSON/SARIF) · `color` · `progress` · `release`. One `test_*.py` per area.

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
- Categorization heuristics **and** layout (`bib`/`sections`/`main_tex`/
  `literature`) are per-paper, loaded from an optional `<paper_dir>/refscan.json`
  (`track.py` / `layout.py`) — never hardcode paper-specific values in the package.
- **Optional deps are tiered extras, lazy-loaded** — `semantic-lite` (model2vec,
  no torch) and `semantic` (sentence-transformers). The base never imports them;
  `semantic.py` loads them inside `get_embedder`. Keep any future heavy feature
  the same way (extra + lazy import), so the core install stays dependency-free.
- New external API sources go in `fetch.py` returning the same dict shape
  (`title/authors/year/arxiv_id/doi`); return `None` on request failure (vs `[]`
  for genuine no-results) so `verify` can distinguish api-error from not-found.

## Feature workflow (established pattern)
1. Branch: `git checkout -b feat/<name>` off `main` (features go on branches).
2. Implement on the branch with tests; a new command = new module + `cmd_*` in
   `cli.py` + a sub-parser + `test_<area>.py`. Keep `uv run --extra dev pytest`
   and `ruff check .` green.
3. Update `README.md` (Capabilities + Commands + test count) and `CHANGELOG.md`.
4. Merge `--no-ff` to `main`, delete the branch, then **Releasing** below.
5. Update `refscan_roadmap.md` (local). Offer the user a push; don't push unasked.

## Releasing
1. Add a `## [X.Y.Z]` section to `CHANGELOG.md`.
2. `refscan release X.Y.Z` (bumps `pyproject.toml` + `__init__.py`, runs tests,
   commits, tags `vX.Y.Z`). Requires an editable install and a clean tree on
   `main`. Add `--push` to publish, or push manually.
3. PyPI is intentionally not published — it's the deliberate go-public step.

## Git
- Stage files **explicitly**; do not `git add -A` (the repo sits next to
  untracked local docs).
- `refscan_roadmap.md` is a gitignored, maintainer-only planning doc — keep it
  current locally, but never commit it.
- CI (`.github/workflows/ci.yml`) runs ruff + a pytest matrix (3.10–3.13) on
  push/PR to `main`. Keep it green.
