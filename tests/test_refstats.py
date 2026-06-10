"""Tests for reference-balance stats."""
from __future__ import annotations

from pathlib import Path

from refscan.bib import BibEntry
from refscan.cli import main
from refscan.refstats import compute_refstats, render_refstats_md


def _e(key: str, year: str, author: str = "Smith, J.") -> BibEntry:
    return BibEntry(key, "article", {"title": "T", "author": author, "year": year})


def test_recency_and_range() -> None:
    entries = [_e("a", "2010"), _e("b", "2020"), _e("c", "2024"), _e("d", "")]
    s = compute_refstats(entries, current_year=2026)
    assert s.total == 4
    assert s.with_year == 3
    assert (s.year_min, s.year_max) == (2010, 2024)
    assert s.median_year == 2020
    # last 5y (2022+): only 2024 -> 1/3
    assert round(s.pct_last_5) == 33
    assert round(s.pct_last_10) == 67   # 2020, 2024


def test_ignores_implausible_years() -> None:
    s = compute_refstats([_e("a", "1850"), _e("b", "3000"), _e("c", "2020")],
                         current_year=2026)
    assert s.with_year == 1 and s.year_min == 2020


def test_self_citation_counts_surname() -> None:
    entries = [_e("mine", "2020", author="Reddy, R. and Other, A."),
               _e("theirs", "2021", author="Nobody, N.")]
    s = compute_refstats(entries, current_year=2026, author_surnames=["Reddy"])
    assert s.self_citations == 1
    assert round(s.self_citation_pct) == 50


def test_self_citation_none_without_author() -> None:
    s = compute_refstats([_e("a", "2020")], current_year=2026)
    assert s.self_citations is None and s.self_citation_pct is None


def test_render_includes_recency_and_histogram() -> None:
    s = compute_refstats([_e("a", "2019"), _e("b", "2019"), _e("c", "2024")],
                         current_year=2026)
    md = render_refstats_md("p", s, scan_date="2026-06-09")
    assert "Reference Balance" in md
    assert "median year" in md
    assert "`2019`" in md and "`2024`" in md


def test_cli_refstats_writes_report(tmp_path: Path) -> None:
    (tmp_path / "references.bib").write_text(
        "@article{a, title={T}, author={Reddy, R}, year={2020}}\n"
        "@article{b, title={U}, author={Other, O}, year={2015}}\n")
    (tmp_path / "paper.tex").write_text(r"\cite{a}\cite{b}")
    rc = main(["refstats", str(tmp_path), "--author", "Reddy"])
    assert rc == 0
    assert (tmp_path / "literature" / "reference_stats.md").exists()
