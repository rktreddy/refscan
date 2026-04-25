# Changelog

All notable changes to refscan will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
