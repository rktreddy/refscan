"""Resolve the on-disk layout of a paper directory.

refscan historically assumed a fixed layout:

    <paper_dir>/paper/references.bib
    <paper_dir>/paper/sections/*.tex
    <paper_dir>/literature/{refs,pdf_text_cache}/

This module makes the **input** locations configurable per paper — via keys in
``<paper_dir>/refscan.json`` or explicit (CLI) overrides — while keeping those
paths as the defaults, so papers using the conventional layout are unaffected.

Configurable keys (all optional, all relative to the paper directory):

    bib         path to references.bib            (default: paper/references.bib)
    sections    a directory, a single .tex file,  (default: paper/sections)
                or a glob of .tex files
    main_tex    extra .tex scanned for \\cite      (default: paper/main.tex)
    literature  refscan's workspace directory     (default: literature)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .track import CONFIG_FILENAME

DEFAULT_BIB = "paper/references.bib"
DEFAULT_SECTIONS = "paper/sections"
DEFAULT_MAIN_TEX = "paper/main.tex"
DEFAULT_LITERATURE = "literature"


@dataclass(frozen=True)
class PaperLayout:
    """Concrete, resolved paths for a single paper."""
    paper_dir: Path
    bib: Path
    section_files: tuple[Path, ...]   # .tex files holding the paper's prose
    main_tex: Path | None             # extra .tex scanned for citations, if present
    literature_dir: Path
    refs_dir: Path
    cache_dir: Path
    auto_bib: bool = False            # bib was auto-discovered (no flag/config/default)
    auto_sections: bool = False       # section files were auto-discovered

    @property
    def cite_files(self) -> list[Path]:
        """Files to scan for ``\\cite`` keys: section files plus main_tex."""
        files = list(self.section_files)
        if self.main_tex is not None and self.main_tex not in files:
            files.append(self.main_tex)
        return files

    # Output artifacts (always under the literature dir).
    @property
    def tracking_md(self) -> Path:
        return self.literature_dir / "reference_tracking.md"

    @property
    def findings_md(self) -> Path:
        return self.literature_dir / "plagiarism_findings.md"

    @property
    def verification_md(self) -> Path:
        return self.literature_dir / "verification_report.md"

    @property
    def sanity_md(self) -> Path:
        return self.literature_dir / "sanity_report.md"

    @property
    def verify_cache(self) -> Path:
        return self.literature_dir / "verify_cache.json"


def _resolve_sections(paper_dir: Path, value: str) -> tuple[Path, ...]:
    """Resolve the ``sections`` setting to a sorted tuple of .tex files.

    Accepts a directory (globs ``*.tex`` inside it), a single .tex file, or a
    glob pattern relative to ``paper_dir``.
    """
    p = paper_dir / value
    if p.is_dir():
        return tuple(sorted(p.glob("*.tex")))
    if p.is_file():
        return (p,)
    return tuple(sorted(paper_dir.glob(value)))


def _read_layout_config(paper_dir: Path) -> dict:
    """Read layout keys from ``<paper_dir>/refscan.json``; {} if absent/malformed."""
    path = paper_dir / CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _discover_bib(paper_dir: Path) -> Path | None:
    """Best-effort find a references .bib when the default location is absent.

    Searches ``paper/`` then the paper root; prefers a file literally named
    ``references.bib``, else the sole ``.bib`` in a directory. Returns ``None``
    if a directory has multiple ambiguous ``.bib`` files (caller should keep the
    default so the user gets a clear "not found" and can configure explicitly).
    """
    for base in (paper_dir / "paper", paper_dir):
        if not base.is_dir():
            continue
        bibs = sorted(b for b in base.glob("*.bib") if b.is_file())
        named = [b for b in bibs if b.name == "references.bib"]
        if named:
            return named[0]
        if len(bibs) == 1:
            return bibs[0]
        if len(bibs) >= 2:
            return None  # ambiguous — don't guess
    return None


def _discover_sections(paper_dir: Path) -> tuple[Path, ...]:
    """Best-effort find paper .tex files when ``paper/sections`` has none.

    Search order: ``paper/sections/*.tex`` → ``paper/*.tex`` → ``*.tex`` at the
    paper root. Returns the .tex files from the first non-empty location.
    """
    for base in (paper_dir / "paper" / "sections", paper_dir / "paper", paper_dir):
        if not base.is_dir():
            continue
        texs = tuple(sorted(t for t in base.glob("*.tex") if t.is_file()))
        if texs:
            return texs
    return ()


def resolve_layout(paper_dir: Path, *, bib: str | None = None,
                   sections: str | None = None,
                   main_tex: str | None = None) -> PaperLayout:
    """Resolve concrete paths for a paper.

    Precedence for each setting: explicit argument > ``refscan.json`` > default.
    The ``bib``/``sections``/``main_tex`` arguments are typically CLI overrides.

    When ``bib``/``sections`` are neither given nor configured **and** the default
    ``paper/...`` location is empty, refscan auto-discovers them (see
    :func:`_discover_bib` / :func:`_discover_sections`) so common layouts work
    with no config. Explicitly set values are never overridden by discovery.
    """
    paper_dir = paper_dir.resolve()
    cfg = _read_layout_config(paper_dir)

    bib_set = bib or cfg.get("bib")
    sections_set = sections or cfg.get("sections")
    main_val = main_tex or cfg.get("main_tex") or DEFAULT_MAIN_TEX
    lit_val = cfg.get("literature") or DEFAULT_LITERATURE

    # bib: use explicit/default; auto-discover only if defaulted and missing.
    bib_path = paper_dir / (bib_set or DEFAULT_BIB)
    auto_bib = False
    if not bib_set and not bib_path.exists():
        found = _discover_bib(paper_dir)
        if found is not None:
            bib_path, auto_bib = found, True

    # sections: use explicit/default; auto-discover only if defaulted and empty.
    section_files = _resolve_sections(paper_dir, sections_set or DEFAULT_SECTIONS)
    auto_sections = False
    if not sections_set and not section_files:
        found_secs = _discover_sections(paper_dir)
        if found_secs:
            section_files, auto_sections = found_secs, True

    literature_dir = paper_dir / lit_val
    main_path = paper_dir / main_val
    return PaperLayout(
        paper_dir=paper_dir,
        bib=bib_path,
        section_files=section_files,
        main_tex=main_path if main_path.exists() else None,
        literature_dir=literature_dir,
        refs_dir=literature_dir / "refs",
        cache_dir=literature_dir / "pdf_text_cache",
        auto_bib=auto_bib,
        auto_sections=auto_sections,
    )
