"""Tests for fetch helpers — focuses on logic that doesn't require network.

The actual network calls (arxiv_search, semantic_scholar_search_metadata)
are skipped here. Those are exercised by integration tests in CI if needed.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from refscan.bib import BibEntry
from refscan.fetch import (
    fetch_paper,
    resolve_pdf_url,
)


def test_resolve_pdf_url_uses_explicit_arxiv_id() -> None:
    e = BibEntry("k", "article", {
        "title": "Some Paper",
        "author": "Smith, J.",
        "year": "2023",
        "journal": "arXiv preprint arXiv:2303.12345",
    })
    url, source = resolve_pdf_url(e, sleep=False)
    assert url == "https://arxiv.org/pdf/2303.12345.pdf"
    assert source == "arxiv-explicit"


def test_resolve_pdf_url_falls_back_to_search_when_no_explicit_id() -> None:
    e = BibEntry("k", "article", {
        "title": "Some Paper",
        "author": "Smith, J.",
        "year": "2023",
    })
    with patch("refscan.fetch.arxiv_search", return_value="2401.99999"), \
         patch("refscan.fetch.semantic_scholar_pdf_url", return_value=None):
        url, source = resolve_pdf_url(e, sleep=False)
    assert url == "https://arxiv.org/pdf/2401.99999.pdf"
    assert source == "arxiv-search"


def test_resolve_pdf_url_falls_back_to_s2() -> None:
    e = BibEntry("k", "article", {
        "title": "Some Paper", "author": "X", "year": "2020",
    })
    with patch("refscan.fetch.arxiv_search", return_value=None), \
         patch("refscan.fetch.semantic_scholar_pdf_url",
                return_value="https://example.com/paper.pdf"):
        url, source = resolve_pdf_url(e, sleep=False)
    assert url == "https://example.com/paper.pdf"
    assert source == "semantic-scholar"


def test_resolve_pdf_url_returns_none_when_no_match() -> None:
    e = BibEntry("k", "article", {
        "title": "Some Paper", "author": "X", "year": "2020",
    })
    with patch("refscan.fetch.arxiv_search", return_value=None), \
         patch("refscan.fetch.semantic_scholar_pdf_url", return_value=None):
        url, source = resolve_pdf_url(e, sleep=False)
    assert url is None
    assert source is None


def test_resolve_pdf_url_skips_s2_when_disabled() -> None:
    e = BibEntry("k", "article", {
        "title": "Some Paper", "author": "X", "year": "2020",
    })
    with patch("refscan.fetch.arxiv_search", return_value=None), \
         patch("refscan.fetch.semantic_scholar_pdf_url") as s2_mock:
        url, source = resolve_pdf_url(e, try_s2=False, sleep=False)
        s2_mock.assert_not_called()
    assert url is None


def test_fetch_paper_skips_already_present_files(tmp_path: Path) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "K1.pdf").write_bytes(b"x" * 6000)
    e = BibEntry("K1", "article", {
        "title": "Some Paper", "author": "X", "year": "2020",
    })
    with patch("refscan.fetch.resolve_pdf_url") as r_mock:
        results = fetch_paper([e], refs, max_workers=1, progress=False)
        r_mock.assert_not_called()  # never resolves an entry that's already on disk
    assert len(results) == 1
    assert results[0]["status"] == "already-present"


def test_fetch_paper_records_not_found(tmp_path: Path) -> None:
    refs = tmp_path / "refs"
    e = BibEntry("Missing", "article", {
        "title": "Imaginary Paper", "author": "X", "year": "2020",
    })
    with patch("refscan.fetch.resolve_pdf_url", return_value=(None, None)):
        results = fetch_paper([e], refs, max_workers=1, progress=False)
    assert len(results) == 1
    assert results[0]["status"] == "not-found"


def test_fetch_paper_runs_downloads_in_parallel(tmp_path: Path) -> None:
    refs = tmp_path / "refs"
    entries = [BibEntry(f"K{i}", "article", {"title": f"Paper {i}", "year": "2020"})
               for i in range(4)]

    def fake_resolve(entry, *args, **kwargs):
        return f"https://example.com/{entry.key}.pdf", "fake"

    def fake_download(url, dest, *args, **kwargs):
        dest.write_bytes(b"x" * 6000)
        return True

    with patch("refscan.fetch.resolve_pdf_url", side_effect=fake_resolve), \
         patch("refscan.fetch.download_pdf", side_effect=fake_download):
        results = fetch_paper(entries, refs, max_workers=4, progress=False)
    assert len(results) == 4
    assert all(r["status"] == "downloaded" for r in results)
    assert all((refs / f"{e.key}.pdf").exists() for e in entries)