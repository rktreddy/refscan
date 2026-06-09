# Changelog

All notable changes to refscan will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **`refscan track` categorization is now config-driven.** Paper-specific
  title/key heuristics that were hardcoded in `track.py` (a list of the
  analogue-computing paper's suspected-fabricated titles, book titles, and
  software keys) are moved out of the package. Categorization now relies on
  general BibTeX signals (`@book`/`@inbook` → skip-book, `@software` →
  skip-software, pre-2000 → pre-arXiv) plus optional per-paper markers loaded
  from `<paper_dir>/refscan.json`: `book_title_markers`, `software_keys`,
  `software_title_markers`, `suspect_title_markers`. A missing or malformed
  config is treated as "no extra heuristics", so the tool works the same on
  any paper with zero configuration. For robust fabrication detection, prefer
  `refscan verify` over the static `suspect_title_markers` pre-filter.
- `categorize()` and `generate_tracking_md()` gained an optional `config`
  parameter (`TrackConfig`); `verify` now also respects the paper's config for
  its skip-book/skip-software logic.

### Added
- `refscan init` writes a `refscan.json` template (empty heuristics) when none
  exists, documenting the available keys.
- `refscan.track` exposes `TrackConfig`, `load_config()`, and
  `write_config_template()`.

### Fixed
- **`refscan verify` no longer mislabels a transient API failure as a
  fabricated reference.** arXiv/Semantic Scholar request failures (network,
  HTTP, or unparseable response) now yield an `api-error` verdict instead of
  `not-found` ("likely fabricated"), and such results are not cached so a
  re-run retries them. A partial failure (one source down, the other returns a
  match) still produces a real verdict.
- Ruff lint errors cleared (unused imports in `cli.py`/`track.py`, placeholder
  f-strings in `release.py`, unused `pytest` import in `tests/test_fetch.py`).

## [0.8.1] — 2026-04-24

### Changed
- ``LICENSE``: copyright holder updated to "Ramakrishna Tipireddy" (was a
  placeholder username).
- ``pyproject.toml``: author name updated to "Ramakrishna Tipireddy" (was
  a placeholder username). Email unchanged.

This is the first release shipped via ``refscan release`` itself —
demonstrates that the v0.8.0 release command works end-to-end on the very
project that introduced it.

## [0.8.0] — 2026-04-24

### Added
- **`refscan release {patch|minor|major|X.Y.Z} [--push] [--no-test] [--dry-run]`** —
  maintainer-only meta-command for shipping new versions of refscan itself.
  Validates the environment (must be on ``main``, working tree clean except
  for the version files, ``CHANGELOG.md`` already has a section for the
  target version), runs the test suite, bumps the version in
  ``pyproject.toml`` and ``src/refscan/__init__.py`` in lockstep, commits
  both with a standard message, tags ``v{new_version}``, and (with
  ``--push``) pushes the branch + tag to ``origin``.
- ``--dry-run`` flag to preview the planned actions without modifying
  anything.
- ``refscan.release`` module exposes ``plan_release()``, ``execute()``,
  and pure helpers (``_bump_version``, ``_replace_version_in_file``,
  ``_changelog_has_version``).

### Notes
- Only works for editable installs (``pip install -e`` or
  ``uv tool install --editable``) since it must locate the source repo.
  Refuses to run otherwise with a clear error message.
- Refuses to release when not on the ``main`` branch.
- Refuses to release when the working tree has uncommitted changes outside
  the three version-tracked files.
- Refuses to release when the new version's CHANGELOG section is missing —
  forces the maintainer to write release notes before shipping.

### Tests
- 13 new tests for version bumping, changelog scanning, and version-file
  replacement (without invoking git or pytest). Total: 86 passing.

## [0.7.0] — 2026-04-24

### Added
- ``fetch.resolve_pdf_url(entry, ...)`` — separates URL resolution (the
  rate-limited part) from the actual download. Returns ``(url, source)``.
- ``fetch.fetch_paper(entries, refs_dir, max_workers=N, ...)`` — bulk-fetch
  helper that runs URL resolution sequentially (respects arXiv/S2 rate
  limits) and PDF downloads in parallel via a ``ThreadPoolExecutor``.
  Returns per-entry result dicts with status, source, and url.
- ``refscan fetch`` now accepts ``--workers N`` (default 5). Parallel
  downloads typically cut bulk-fetch wall time by 30–60% on a corpus of
  100+ references.

### Changed
- ``refscan fetch`` CLI rewritten to use ``fetch_paper`` internally; output
  now shows a resolution phase followed by a download phase. New summary
  line distinguishes ``downloaded``/``download-failed``/``not-found``.
- ``fetch.fetch_entry`` is preserved as a backwards-compatible single-entry
  wrapper (used elsewhere in the codebase) but now delegates to
  ``resolve_pdf_url`` + ``download_pdf`` internally.

### Tests
- 8 new tests for ``resolve_pdf_url`` and ``fetch_paper`` (uses mocking to
  avoid network). Total: 73 passing.

## [0.6.0] — 2026-04-24

### Added
- **`refscan watch`** — file watcher for active drafting. Polls
  ``paper/sections/*.tex`` (and ``main.tex`` if present) at a configurable
  interval; whenever a file's mtime changes, re-runs the plagiarism scan and
  prints a compact terminal summary (top-N matches with score, run length,
  reference, and shingle preview). Stdlib-only — no ``watchdog`` dependency.
- ``scan.render_findings_terminal(result, top_n, width)`` — single-line-per-
  finding summary suitable for terminal display.

### CLI
- New: ``refscan watch <paper_dir> [--interval N] [--top N] [--shingle-n N]
  [--min-run M]``. Default interval 1s, default top 5.

### Tests
- 3 new tests for the terminal renderer (no-findings, with-findings,
  top-N capping). Total: 65 passing.

## [0.5.0] — 2026-04-24

### Added
- **`refscan sanity-stats`** — bib hygiene report. Surfaces problems before
  they reach reviewers:
  - 🔴 **errors**: cited keys not defined, duplicate keys, missing title.
  - 🟡 **warnings**: unused entries (bib bloat), duplicate titles (likely
    duplicate refs with different keys), missing author/year for normal
    entries, year too old (< 1900) or in the future, stub authors
    (just "and others" with nothing else).
  - ℹ️ **info**: missing year/author for software citations (`@misc`,
    `@software`, `@manual`, `@online`, `@techreport`) — often legitimately
    unspecified.
- Output: `literature/sanity_report.md`, grouped by severity then category.
- Exit code 1 on any errors; 0 otherwise — useful in CI.

### New module
- ``refscan.sanity`` — ``BibIssue`` dataclass, ``check_bib()``,
  ``render_sanity_md()``, ``run_sanity()``.

### Tests
- 12 new tests covering each check independently and the renderer.
  Total: 62 passing.

## [0.4.0] — 2026-04-24

### Added
- ``scan.confidence_score(shingle_text, run_len, num_refs_with_phrase)`` — a
  0–1 score combining three factors:
  - **Length**: longer runs are stronger signal
    (``1 - exp(-run_len / 10)``).
  - **Non-stopword density**: shingles dominated by stopwords are noise.
  - **Phrase rarity**: phrases shared by many references in the cited corpus
    are likely technical terminology, not concerning paraphrase
    (``1 / sqrt(num_refs_with_phrase)``).
- Each plagiarism finding is now annotated with its score and findings are
  sorted by score (descending) instead of run length.
- New **🔝 Top N concerning matches** section at the top of every
  ``plagiarism_findings.md`` report — surfaces the highest-confidence matches
  in a compact table (#, score, words, ref, section, shingle) for quick
  triage. Default N = 10.
- Per-reference grouping now sorts by max score within the reference and
  shows the score for every listed match.

### Changed
- ``scan.scan()`` now computes per-finding scores and sorts findings by
  ``-score, -run_len, section`` instead of ``-run_len, section``.
- Report headings updated to explain the new score model.

### Tests
- 5 new tests for ``confidence_score``: length effect, stopword penalty,
  rarity penalty, [0, 1] bound, all-stopword zero-signal edge case. Total: 50
  passing.

## [0.3.0] — 2026-04-24

### Added
- ``textproc.collapse_whitespace(text)`` — strip all whitespace from text;
  primitive for substring-matching against pdftotext output where word
  boundaries are unreliable due to letter-spacing.
- ``textproc.title_word_match(bib_title, pdf_text)`` — robust title-overlap
  heuristic that combines word-set matching with substring fallback against
  the whitespace-collapsed text. Catches cases like "DARTS: D IFFERENTIABLE
  A RCHITECTURE S EARCH" where each word's first letter is detached.

### Changed
- ``verify._title_overlap`` now uses ``title_word_match`` so verification
  scoring is robust to letter-spaced PDF artifacts in API responses.
- Documented ``repair_letter_spacing`` to clarify it handles long single-
  letter runs only; for partial-word patterns, ``title_word_match`` is the
  right tool.

### Tests
- 9 new tests for the textproc additions and edge cases. Total: 45 passing.

### Why this was bumped to a minor (0.3 vs. 0.2.1) release
Adding ``title_word_match`` and changing ``_title_overlap``'s underlying
algorithm changes verification verdicts in some cases (typically: more
matches recognized, fewer false-negative "not-found" verdicts on titles with
letter-spaced PDFs). That's a behavior change, not a bug fix.

## [0.2.0] — 2026-04-24

### Added
- **`refscan verify`** — query arXiv + Semantic Scholar per bib entry and grade
  the match against claimed title / first-author / year. Verdicts: `verified`,
  `metadata-drift`, `weak-match`, `not-found`, `skipped`. Output:
  `literature/verification_report.md` with best-match metadata inline so the
  user can spot-fix or remove fabricated entries. Always queries the API even
  when a PDF is already downloaded (catches substitute PDFs).
- Per-entry result cache at `literature/verify_cache.json`. Use `--refresh` to
  re-query.
- `arxiv_search_metadata()` and `semantic_scholar_search_metadata()` in
  `refscan.fetch` — return full candidate metadata (title, authors, year,
  arXiv ID, DOI), supporting verification logic.
- Semantic Scholar API key support via `REFSCAN_S2_API_KEY` environment
  variable. Without a key, the unauthenticated rate limit (very strict) will
  likely throttle after a few requests; the report flags this case.
- 429 detection: once Semantic Scholar returns a rate-limit error, subsequent
  S2 calls are skipped for the rest of the run and the report adds an explicit
  caveat.

### Changed
- Default user agent updated to `refscan/0.2 (mailto:rktreddy@gmail.com)` per
  Semantic Scholar's contact-info recommendation.
- `_http_get()` now returns `(body, status_code)` instead of `body | None`,
  enabling 429-aware fallback. All call sites updated.
- `S2_DELAY_S` raised from 1.5s to 3.0s (more conservative for unauthenticated
  use).

### Tests
- 17 new tests for verify scoring, verdict logic, and markdown rendering.
  Total tests now 36; all passing.

## [0.1.0] — 2026-04-24

Initial release. Born out of plagiarism-scan work on a 5-paper analogue-computing
research program; consolidated from prototype scripts into a packaged CLI.

### Added
- **`refscan init`** — scaffold a paper's `literature/refs/` and
  `literature/pdf_text_cache/` directories and write an initial
  `reference_tracking.md`.
- **`refscan fetch`** — auto-download reference PDFs from arXiv (by explicit ID
  if present in the bib, else by title+author search) and Semantic Scholar
  (open-access PDF or arXiv preprint via `externalIds`). Rate-limited per each
  service's published guidelines.
- **`refscan track`** — regenerate `reference_tracking.md` for a paper.
  Categorizes each cited reference as `downloaded`, `fetchable`,
  `verify-exists` (likely fabricated, generic title heuristic), `pre-arxiv`,
  `skip-book`, or `skip-software`.
- **`refscan scan`** — extract text from every reference PDF (via `pdftotext`)
  and shingle-match it against each LaTeX section in `paper/sections/`.
  Default: 6-word shingles, 6-word minimum run, generic-phrase filter on.
  Output: `literature/plagiarism_findings.md`.
- **`refscan overlap`** — cross-paper overlap detection across two or more
  paper directories. Useful as a self-plagiarism check for a research program.

### Modules
- `refscan.bib` — minimal BibTeX parser supporting brace- and quote-delimited
  values; handles the subset used by typical ML/CS papers.
- `refscan.textproc` — LaTeX strip, Unicode + ligature normalization,
  tokenization, n-gram shingling, letter-spaced-title repair.
- `refscan.fetch` — arXiv API client + Semantic Scholar API client + HTTP
  download with min-size validation.
- `refscan.track` — per-paper tracking-file generator with bucket logic.
- `refscan.scan` — PDF text extraction (mtime-cached) + shingle indexing +
  maximal-run finder + generic-phrase filter + markdown report renderer.
- `refscan.overlap` — pairwise n-gram overlap + maximal-run extraction across
  multiple papers.
- `refscan.cli` — argparse dispatcher.

### Tests
- 19 unit tests covering bib parsing, text processing, shingle logic, and
  generic-phrase detection. All passing.

### Dependencies
- Standard library only at runtime.
- System dependency: `pdftotext` (poppler) for PDF text extraction.
- Dev dependency: `pytest>=7.0`, `ruff>=0.1`.

### Known limitations
- Only handles plain BibTeX (not BibLaTeX advanced features such as
  `\addbibresource`, cross-references, or string substitutions).
- PDF text extraction inherits `pdftotext` quirks; the letter-spacing repair
  heuristic catches common cases but pathological PDFs may still produce noisy
  tokens.
- Fetch is sequential; ~7 minutes for ~120 references against arXiv+S2.
- Catches only paraphrase against *cited* references; cannot detect overlap
  with uncited external work (use a paid service like iThenticate for that).
