# Changelog

All notable changes to refscan will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
