"""Tests for paper-layout resolution (default, config, and CLI overrides)."""
from __future__ import annotations

import json
from pathlib import Path

from refscan.layout import resolve_layout


def _write(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# --- defaults reproduce the historical layout ----------------------------

def test_default_layout(tmp_path: Path) -> None:
    _write(tmp_path / "paper" / "references.bib")
    _write(tmp_path / "paper" / "sections" / "intro.tex")
    _write(tmp_path / "paper" / "sections" / "method.tex")
    lay = resolve_layout(tmp_path)
    assert lay.bib == (tmp_path / "paper" / "references.bib").resolve()
    assert lay.section_files == (
        (tmp_path / "paper" / "sections" / "intro.tex").resolve(),
        (tmp_path / "paper" / "sections" / "method.tex").resolve(),
    )
    assert lay.refs_dir == (tmp_path / "literature" / "refs").resolve()
    assert lay.cache_dir == (tmp_path / "literature" / "pdf_text_cache").resolve()
    assert lay.main_tex is None  # no paper/main.tex present


def test_main_tex_picked_up_when_present(tmp_path: Path) -> None:
    _write(tmp_path / "paper" / "references.bib")
    _write(tmp_path / "paper" / "sections" / "intro.tex")
    _write(tmp_path / "paper" / "main.tex")
    lay = resolve_layout(tmp_path)
    assert lay.main_tex == (tmp_path / "paper" / "main.tex").resolve()
    # cite_files = sections + main_tex
    assert (tmp_path / "paper" / "main.tex").resolve() in lay.cite_files
    assert len(lay.cite_files) == 2


# --- sections: directory / single file / glob ----------------------------

def test_sections_single_file_via_config(tmp_path: Path) -> None:
    _write(tmp_path / "references.bib")
    _write(tmp_path / "paper.tex")
    _write(tmp_path / "refscan.json", json.dumps({"bib": "references.bib",
                                                  "sections": "paper.tex"}))
    lay = resolve_layout(tmp_path)
    assert lay.bib == (tmp_path / "references.bib").resolve()
    assert lay.section_files == ((tmp_path / "paper.tex").resolve(),)
    assert lay.cite_files == [(tmp_path / "paper.tex").resolve()]


def test_sections_glob(tmp_path: Path) -> None:
    _write(tmp_path / "chapters" / "a.tex")
    _write(tmp_path / "chapters" / "b.tex")
    _write(tmp_path / "chapters" / "notes.md")  # ignored
    lay = resolve_layout(tmp_path, sections="chapters/*.tex")
    assert lay.section_files == (
        (tmp_path / "chapters" / "a.tex").resolve(),
        (tmp_path / "chapters" / "b.tex").resolve(),
    )


def test_sections_missing_resolves_empty(tmp_path: Path) -> None:
    lay = resolve_layout(tmp_path)  # no paper/sections at all
    assert lay.section_files == ()


# --- precedence: CLI > config > default ----------------------------------

def test_cli_overrides_config_and_default(tmp_path: Path) -> None:
    _write(tmp_path / "custom.bib")
    _write(tmp_path / "refscan.json", json.dumps({"bib": "config.bib"}))
    lay = resolve_layout(tmp_path, bib="custom.bib")
    assert lay.bib == (tmp_path / "custom.bib").resolve()


def test_config_overrides_default(tmp_path: Path) -> None:
    _write(tmp_path / "refscan.json", json.dumps({"literature": "lit"}))
    lay = resolve_layout(tmp_path)
    assert lay.literature_dir == (tmp_path / "lit").resolve()
    assert lay.refs_dir == (tmp_path / "lit" / "refs").resolve()


def test_malformed_config_falls_back_to_defaults(tmp_path: Path) -> None:
    _write(tmp_path / "refscan.json", "{ not json")
    lay = resolve_layout(tmp_path)
    assert lay.bib == (tmp_path / "paper" / "references.bib").resolve()


def test_categorization_only_config_does_not_break_layout(tmp_path: Path) -> None:
    # A refscan.json with only marker keys (the init template) → defaults hold.
    _write(tmp_path / "refscan.json", json.dumps({"book_title_markers": ["x"]}))
    lay = resolve_layout(tmp_path)
    assert lay.bib == (tmp_path / "paper" / "references.bib").resolve()
    assert lay.section_files == ()


# --- output artifact paths -----------------------------------------------

def test_output_paths_under_literature(tmp_path: Path) -> None:
    lay = resolve_layout(tmp_path)
    lit = (tmp_path / "literature").resolve()
    assert lay.tracking_md == lit / "reference_tracking.md"
    assert lay.findings_md == lit / "plagiarism_findings.md"
    assert lay.verification_md == lit / "verification_report.md"
    assert lay.sanity_md == lit / "sanity_report.md"
    assert lay.verify_cache == lit / "verify_cache.json"
