"""Tests for the progress-bar helper and fetch's progress output path."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from refscan.bib import BibEntry
from refscan.fetch import fetch_paper
from refscan.progress import bar


def test_bar_empty() -> None:
    assert bar(0, 10, "go", width=10) == "go [░░░░░░░░░░] 0/10"


def test_bar_half() -> None:
    assert bar(5, 10, "go", width=10) == "go [█████░░░░░] 5/10"


def test_bar_full() -> None:
    assert bar(10, 10, "go", width=10) == "go [██████████] 10/10"


def test_bar_clamps_and_handles_zero_total() -> None:
    assert bar(0, 0, "x", width=4) == "x [░░░░] 0/1"      # total floored to 1
    assert bar(99, 10, width=4) == "[████] 99/10"          # over-100% clamps fill, no label


def test_fetch_paper_progress_true_does_not_crash(tmp_path: Path) -> None:
    # Non-TTY (pytest captures stdout) -> line mode; must still produce results.
    refs = tmp_path / "refs"
    e = BibEntry("K1", "article", {"title": "P", "year": "2020"})
    with patch("refscan.fetch.resolve_pdf_url", return_value=("https://x/p.pdf", "openalex")), \
         patch("refscan.fetch.download_pdf", return_value=True):
        results = fetch_paper([e], refs, max_workers=1, progress=True)
    assert results[0]["status"] == "downloaded"
