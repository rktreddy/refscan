"""Tests for fetch helpers — focuses on logic that doesn't require network.

The actual network calls (arxiv_search, semantic_scholar_search_metadata)
are skipped here. Those are exercised by integration tests in CI if needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from refscan.bib import BibEntry
from refscan.fetch import (
    crossref_search_metadata,
    download_pdf,
    fetch_paper,
    openalex_pdf_url,
    openalex_search_metadata,
    resolve_pdf_url,
    unpaywall_pdf_url,
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


def test_resolve_pdf_url_falls_back_to_openalex() -> None:
    e = BibEntry("k", "article", {"title": "Some Paper", "author": "X", "year": "2020"})
    with patch("refscan.fetch.arxiv_search", return_value=None), \
         patch("refscan.fetch.semantic_scholar_pdf_url", return_value=None), \
         patch("refscan.fetch.openalex_pdf_url", return_value="https://ex.com/p.pdf"):
        url, source = resolve_pdf_url(e, sleep=False)
    assert url == "https://ex.com/p.pdf"
    assert source == "openalex"


def test_resolve_pdf_url_returns_none_when_no_match() -> None:
    e = BibEntry("k", "article", {
        "title": "Some Paper", "author": "X", "year": "2020",
    })
    with patch("refscan.fetch.arxiv_search", return_value=None), \
         patch("refscan.fetch.semantic_scholar_pdf_url", return_value=None), \
         patch("refscan.fetch.openalex_pdf_url", return_value=None):
        url, source = resolve_pdf_url(e, sleep=False)
    assert url is None
    assert source is None


# --- OpenAlex source + download hardening --------------------------------

_OA_META = json.dumps({"results": [{
    "title": "Neural Ordinary Differential Equations",
    "publication_year": 2018,
    "authorships": [{"author": {"display_name": "Ricky T. Q. Chen"}}],
    "doi": "https://doi.org/10.5555/abc",
}]}).encode()


def test_openalex_search_metadata_parses() -> None:
    with patch("refscan.fetch._http_get", return_value=(_OA_META, 200)):
        out = openalex_search_metadata("Neural Ordinary Differential Equations")
    assert out[0]["title"] == "Neural Ordinary Differential Equations"
    assert out[0]["year"] == "2018"
    assert out[0]["doi"] == "10.5555/abc"          # https://doi.org/ stripped
    assert "Ricky T. Q. Chen" in out[0]["authors"]


def test_openalex_search_metadata_request_failure_returns_none() -> None:
    with patch("refscan.fetch._http_get", return_value=(None, None)):
        assert openalex_search_metadata("X") is None


def test_openalex_search_metadata_carries_retracted() -> None:
    payload = json.dumps({"results": [{
        "title": "A Retracted Paper", "publication_year": 2015, "is_retracted": True,
    }]}).encode()
    with patch("refscan.fetch._http_get", return_value=(payload, 200)):
        out = openalex_search_metadata("A Retracted Paper")
    assert out[0]["retracted"] is True


def test_openalex_search_metadata_defaults_retracted_false() -> None:
    with patch("refscan.fetch._http_get", return_value=(_OA_META, 200)):  # no is_retracted key
        out = openalex_search_metadata("Neural Ordinary Differential Equations")
    assert out[0]["retracted"] is False


def test_openalex_pdf_url_returns_oa_pdf() -> None:
    payload = json.dumps({"results": [{
        "title": "Neural Ordinary Differential Equations",
        "best_oa_location": {"pdf_url": "https://example.com/neural.pdf"},
    }]}).encode()
    with patch("refscan.fetch._http_get", return_value=(payload, 200)):
        url = openalex_pdf_url("Neural Ordinary Differential Equations")
    assert url == "https://example.com/neural.pdf"


def test_download_pdf_rejects_non_pdf(tmp_path: Path) -> None:
    html = b"<!DOCTYPE html><html>" + b"x" * 6000
    with patch("refscan.fetch._http_get", return_value=(html, 200)):
        ok = download_pdf("http://x", tmp_path / "a.pdf")
    assert ok is False
    assert not (tmp_path / "a.pdf").exists()


def test_download_pdf_accepts_pdf(tmp_path: Path) -> None:
    pdf = b"%PDF-1.5\n" + b"x" * 6000
    with patch("refscan.fetch._http_get", return_value=(pdf, 200)):
        ok = download_pdf("http://x", tmp_path / "a.pdf")
    assert ok is True
    assert (tmp_path / "a.pdf").read_bytes()[:5] == b"%PDF-"


# --- Crossref + Unpaywall ------------------------------------------------

def test_crossref_search_metadata_parses() -> None:
    payload = json.dumps({"message": {"items": [{
        "title": ["Deep Residual Learning for Image Recognition"],
        "author": [{"given": "Kaiming", "family": "He"}],
        "issued": {"date-parts": [[2016]]},
        "DOI": "10.1109/CVPR.2016.90",
    }]}}).encode()
    with patch("refscan.fetch._http_get", return_value=(payload, 200)):
        out = crossref_search_metadata("Deep Residual Learning")
    assert out[0]["title"].startswith("Deep Residual")
    assert out[0]["year"] == "2016"
    assert out[0]["doi"] == "10.1109/CVPR.2016.90"
    assert "Kaiming He" in out[0]["authors"]


def test_crossref_request_failure_returns_none() -> None:
    with patch("refscan.fetch._http_get", return_value=(None, None)):
        assert crossref_search_metadata("X") is None


def test_unpaywall_pdf_url_returns_pdf(monkeypatch) -> None:
    monkeypatch.setenv("REFSCAN_CONTACT_EMAIL", "me@example.com")  # required by Unpaywall
    payload = json.dumps({"best_oa_location": {"url_for_pdf": "https://ex.com/oa.pdf"}}).encode()
    with patch("refscan.fetch._http_get", return_value=(payload, 200)):
        assert unpaywall_pdf_url("10.1/abc") == "https://ex.com/oa.pdf"


def test_unpaywall_no_doi_returns_none() -> None:
    assert unpaywall_pdf_url("") is None


def test_unpaywall_skips_without_contact_email(monkeypatch) -> None:
    monkeypatch.delenv("REFSCAN_CONTACT_EMAIL", raising=False)
    # No email set -> skipped before any network call (no default address sent).
    with patch("refscan.fetch._http_get", side_effect=AssertionError("should not be called")):
        assert unpaywall_pdf_url("10.1/abc") is None


def test_contact_email_no_personal_default(monkeypatch) -> None:
    from refscan.fetch import _contact_email
    monkeypatch.delenv("REFSCAN_CONTACT_EMAIL", raising=False)
    assert _contact_email() == ""        # nothing shipped
    monkeypatch.setenv("REFSCAN_CONTACT_EMAIL", "you@example.com")
    assert _contact_email() == "you@example.com"


def test_resolve_pdf_url_falls_back_to_unpaywall_via_doi() -> None:
    e = BibEntry("k", "article", {"title": "J", "author": "X", "year": "2020",
                                   "doi": "10.1/abc"})
    with patch("refscan.fetch.arxiv_search", return_value=None), \
         patch("refscan.fetch.semantic_scholar_pdf_url", return_value=None), \
         patch("refscan.fetch.openalex_pdf_url", return_value=None), \
         patch("refscan.fetch.unpaywall_pdf_url", return_value="https://ex.com/u.pdf"):
        url, source = resolve_pdf_url(e, sleep=False)
    assert url == "https://ex.com/u.pdf"
    assert source == "unpaywall"


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


def test_fetch_paper_skips_unsafe_key_without_escaping(tmp_path: Path) -> None:
    refs = tmp_path / "lit" / "refs"
    refs.mkdir(parents=True)
    e = BibEntry("../../evil", "article", {"title": "Sneaky", "year": "2020"})
    with patch("refscan.fetch.resolve_pdf_url") as r_mock, \
         patch("refscan.fetch.download_pdf") as d_mock:
        results = fetch_paper([e], refs, max_workers=1, progress=False)
        r_mock.assert_not_called()   # never resolves an unsafe key
        d_mock.assert_not_called()   # never downloads it
    assert results[0]["status"] == "unsafe-key"
    # Nothing was written anywhere outside refs/ (the traversal target).
    assert not (tmp_path / "evil.pdf").exists()


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