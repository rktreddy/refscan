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


def resolve_layout(paper_dir: Path, *, bib: str | None = None,
                   sections: str | None = None,
                   main_tex: str | None = None) -> PaperLayout:
    """Resolve concrete paths for a paper.

    Precedence for each setting: explicit argument > ``refscan.json`` > default.
    The ``bib``/``sections``/``main_tex`` arguments are typically CLI overrides.
    """
    paper_dir = paper_dir.resolve()
    cfg = _read_layout_config(paper_dir)

    bib_val = bib or cfg.get("bib") or DEFAULT_BIB
    sections_val = sections or cfg.get("sections") or DEFAULT_SECTIONS
    main_val = main_tex or cfg.get("main_tex") or DEFAULT_MAIN_TEX
    lit_val = cfg.get("literature") or DEFAULT_LITERATURE

    literature_dir = paper_dir / lit_val
    main_path = paper_dir / main_val
    return PaperLayout(
        paper_dir=paper_dir,
        bib=paper_dir / bib_val,
        section_files=_resolve_sections(paper_dir, sections_val),
        main_tex=main_path if main_path.exists() else None,
        literature_dir=literature_dir,
        refs_dir=literature_dir / "refs",
        cache_dir=literature_dir / "pdf_text_cache",
    )
