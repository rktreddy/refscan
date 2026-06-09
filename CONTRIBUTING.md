# Contributing to refscan

Thanks for your interest in improving refscan. It's a small, focused CLI for
reference-PDF collection and paper-vs-references plagiarism scanning. Bug fixes,
new fetch sources, and output improvements are all welcome.

## Development setup

```bash
git clone https://github.com/rktreddy/refscan
cd refscan

# Recommended: uv (no separate venv step needed)
uv run --extra dev pytest          # installs project + dev deps, runs tests

# Or pip into a virtualenv
pip install -e ".[dev]"
pytest
```

Runtime system dependency: **`pdftotext`** (from poppler) — `brew install poppler`
(macOS) or `apt install poppler-utils` (Debian/Ubuntu). It is only needed at
runtime for `refscan scan`; the test suite does not require it.

## Tests and linting

Both must pass before a PR can merge — CI enforces them on Python 3.10–3.13.

```bash
uv run --extra dev pytest          # or: pytest
uv run --extra dev ruff check .    # or: ruff check .
```

- Add or update tests for any behavior change. Network calls (arXiv/Semantic
  Scholar) are **not** exercised in tests — mock them, as the existing
  `tests/` do, and keep the suite offline and fast.
- Run `ruff check .` locally; `ruff` is the only linter the project uses (its
  config lives in `pyproject.toml`). Ignore unrelated warnings from other
  linters your editor may run.

## Code conventions

- **Standard library only at runtime.** `pyproject.toml` has no runtime
  dependencies, and that's a feature — keep it that way. Anything you need only
  for tests/lint goes in the `dev` optional-dependency group.
- **Python 3.10+.** Don't use syntax or stdlib APIs newer than 3.10. (This is
  also why per-paper config is JSON, not TOML — there's no `tomllib` on 3.10.)
- **Type hints** on public function signatures; **a docstring** on each public
  function and module.
- Line length 100 (enforced by ruff config).
- `bib.parse_bib` is a deliberately minimal BibTeX parser (one level of brace
  nesting, plain BibTeX). Keep it minimal rather than pulling in a BibLaTeX
  dependency.
- Categorization heuristics are **per-paper**, loaded from an optional
  `<paper_dir>/refscan.json`. Never hardcode paper-specific titles or keys in
  the package.

## Project layout

```
src/refscan/
  cli.py        # argparse dispatcher (one cmd_* per subcommand)
  bib.py        # BibTeX parsing + safe reference-path helpers
  fetch.py      # arXiv + Semantic Scholar lookups and downloads
  track.py      # reference_tracking.md generator + per-paper config
  scan.py       # PDF text extraction + shingle matching + scoring
  verify.py     # bib-entry verification against arXiv/S2
  sanity.py     # bib hygiene checks
  overlap.py    # cross-paper overlap
  textproc.py   # LaTeX strip, normalization, tokenization, shingles
  release.py    # maintainer-only release command
tests/          # test_*.py — most source modules have a matching test module
```

## Commits and pull requests

- Keep commits focused; use a short, descriptive subject, ideally prefixed with
  the area (`fetch:`, `scan:`, `docs:`, `ci:`, …) to match existing history.
- Stage files explicitly rather than `git add -A` (the working tree may sit
  next to untracked local notes).
- Update `CHANGELOG.md` for any user-visible change — add bullets under a
  `## [Unreleased]` heading (create it if absent) following the
  [Keep a Changelog](https://keepachangelog.com/) style.
- Open the PR against `main`. Ensure CI (ruff + pytest matrix) is green.

## Releasing (maintainers only)

Releases are cut with the built-in command, from a clean tree on `main`:

1. Rename the `## [Unreleased]` CHANGELOG section to `## [X.Y.Z] — DATE`.
2. `refscan release X.Y.Z` — bumps the version in `pyproject.toml` and
   `__init__.py`, runs tests, commits, and tags `vX.Y.Z`. Add `--push` to
   publish, or push manually afterward.

## Reporting issues

Open an issue at https://github.com/rktreddy/refscan/issues with the command you
ran, the bib/section input if relevant, and what you expected vs. what happened.
