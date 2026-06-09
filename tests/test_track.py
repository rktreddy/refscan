"""Tests for track module — config-driven categorization and template writing."""
from __future__ import annotations

import json
from pathlib import Path

from refscan.bib import BibEntry
from refscan.track import (
    CONFIG_FILENAME,
    DEFAULT_CONFIG,
    TrackConfig,
    categorize,
    generate_tracking_md,
    load_config,
    write_config_template,
)


def _entry(key: str, title: str = "Some Paper", year: str = "2020",
           entry_type: str = "article") -> BibEntry:
    return BibEntry(key, entry_type, {"title": title, "author": "Smith, J.", "year": year})


# --- general (zero-config) signals ---------------------------------------

def test_pdf_present_is_downloaded() -> None:
    assert categorize(_entry("k"), pdf_present=True) == "downloaded"


def test_book_entry_type_is_skip_book() -> None:
    assert categorize(_entry("k", entry_type="book"), pdf_present=False) == "skip-book"
    assert categorize(_entry("k", entry_type="inbook"), pdf_present=False) == "skip-book"


def test_software_entry_type_is_skip_software() -> None:
    assert categorize(_entry("k", entry_type="software"), pdf_present=False) == "skip-software"


def test_pre_2000_is_pre_arxiv() -> None:
    assert categorize(_entry("k", year="1995"), pdf_present=False) == "pre-arxiv"


def test_default_is_fetchable() -> None:
    assert categorize(_entry("k"), pdf_present=False) == "fetchable"


def test_no_suspect_bucket_without_config() -> None:
    # The analogue-paper's old hardcoded markers must no longer fire by default.
    e = _entry("k", title="Memristor-based analog computing for fast inference", year="2023")
    assert categorize(e, pdf_present=False) == "fetchable"


# --- config-driven markers ------------------------------------------------

def test_config_software_key() -> None:
    cfg = TrackConfig(software_keys=frozenset({"jax"}))
    assert categorize(_entry("JAX"), pdf_present=False, config=cfg) == "skip-software"


def test_config_book_title_marker() -> None:
    cfg = TrackConfig(book_title_markers=("nonlinear dynamics and chaos",))
    e = _entry("k", title="Nonlinear Dynamics and Chaos", entry_type="article")
    assert categorize(e, pdf_present=False, config=cfg) == "skip-book"


def test_config_suspect_marker_only_for_recent() -> None:
    cfg = TrackConfig(suspect_title_markers=("coupled oscillator networks for",))
    recent = _entry("k", title="Coupled Oscillator Networks for Inference", year="2023")
    old = _entry("k", title="Coupled Oscillator Networks for Inference", year="1999")
    assert categorize(recent, pdf_present=False, config=cfg) == "verify-exists"
    # Pre-2000 short-circuits to pre-arxiv before the suspect check.
    assert categorize(old, pdf_present=False, config=cfg) == "pre-arxiv"


# --- config loading -------------------------------------------------------

def test_load_config_missing_returns_default(tmp_path: Path) -> None:
    assert load_config(tmp_path) is DEFAULT_CONFIG


def test_load_config_malformed_returns_default(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("{ not valid json")
    assert load_config(tmp_path) is DEFAULT_CONFIG


def test_load_config_reads_and_lowercases(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(json.dumps({
        "book_title_markers": ["Some BOOK Title"],
        "software_keys": ["JAX", "PyTorch"],
        "suspect_title_markers": ["Fabricated Thing"],
    }))
    cfg = load_config(tmp_path)
    assert cfg.book_title_markers == ("some book title",)
    assert cfg.software_keys == frozenset({"jax", "pytorch"})
    assert cfg.suspect_title_markers == ("fabricated thing",)
    assert cfg.software_title_markers == ()  # absent key -> empty


def test_write_config_template_creates_then_skips(tmp_path: Path) -> None:
    written = write_config_template(tmp_path)
    assert written == tmp_path / CONFIG_FILENAME
    assert written.exists()
    # Template is valid JSON and loads cleanly (empty heuristics).
    assert load_config(tmp_path) == DEFAULT_CONFIG
    # Second call is a no-op (does not clobber an existing config).
    assert write_config_template(tmp_path) is None


# --- end-to-end tracking md ----------------------------------------------

def test_generate_tracking_md_uses_paper_config(tmp_path: Path) -> None:
    paper_dir = tmp_path / "mypaper"
    (paper_dir / "paper").mkdir(parents=True)
    (paper_dir / "literature" / "refs").mkdir(parents=True)
    (paper_dir / "paper" / "references.bib").write_text(
        "@article{realkey, title={A Real Paper}, author={Smith, J.}, year={2023}}\n"
        "@misc{toolkey, title={MyToolkit Docs}, year={2023}}\n"
    )
    (paper_dir / CONFIG_FILENAME).write_text(json.dumps({
        "software_title_markers": ["mytoolkit"],
    }))
    path, counts = generate_tracking_md(paper_dir, "mypaper", scan_date="2026-06-09")
    assert path.exists()
    assert counts["skip-software"] == 1   # toolkey matched via config marker
    assert counts["fetchable"] == 1       # realkey
