"""Tests for verify module — verdict logic, scoring, markdown rendering.

Network calls are not exercised; verify_entry/verify_paper are skipped in
favor of direct testing of the pure scoring + verdict functions.
"""
from __future__ import annotations

from unittest.mock import patch

from refscan.bib import BibEntry
from refscan.verify import (
    APIResult,
    VerifyResult,
    _author_in,
    _score_candidate,
    _title_overlap,
    _verdict_from,
    render_verification_md,
    verify_entry,
)


def test_title_overlap_full_match() -> None:
    ov = _title_overlap("Neural Ordinary Differential Equations",
                        "Neural Ordinary Differential Equations")
    assert ov == 1.0


def test_title_overlap_partial() -> None:
    ov = _title_overlap("Neural Ordinary Differential Equations",
                        "On Neural Ordinary Equations")
    # bib words {neural, ordinary, differential, equations}
    # candidate words {neural, ordinary, equations}  -> 3/4 = 0.75
    assert 0.7 < ov < 0.8


def test_title_overlap_zero() -> None:
    ov = _title_overlap("Neural Ordinary Differential Equations",
                        "An Image is Worth Sixteen by Sixteen Words")
    assert ov == 0.0


def test_title_overlap_empty_bib() -> None:
    assert _title_overlap("", "anything") == 0.0


def test_author_in_found() -> None:
    assert _author_in(["Yann LeCun", "Yoshua Bengio"], "LeCun")


def test_author_in_case_insensitive() -> None:
    assert _author_in(["yann lecun"], "LeCun")


def test_author_in_not_found() -> None:
    assert not _author_in(["Bob Smith"], "Wright")


def test_author_in_empty_surname_skips() -> None:
    # Empty surname returns True (don't penalize when nothing to check)
    assert _author_in(["Bob Smith"], "")


def test_score_candidate_perfect() -> None:
    e = BibEntry("k", "article", {"title": "Foo Bar Baz Quux",
                                    "author": "Smith, Jane", "year": "2020"})
    candidate = {"title": "Foo Bar Baz Quux", "authors": ["Jane Smith"], "year": "2020"}
    r = _score_candidate(e, candidate, "arxiv")
    assert r.title_overlap == 1.0
    assert r.author_match
    assert r.year_diff == 0


def test_score_candidate_year_drift() -> None:
    e = BibEntry("k", "article", {"title": "Foo Bar Baz Quux",
                                    "author": "Smith, Jane", "year": "2020"})
    candidate = {"title": "Foo Bar Baz Quux", "authors": ["Jane Smith"], "year": "2023"}
    r = _score_candidate(e, candidate, "arxiv")
    assert r.year_diff == 3


def test_verdict_from_verified() -> None:
    r = APIResult(source="arxiv", title="t", authors=["a"], year="2020",
                  title_overlap=0.9, author_match=True, year_diff=0)
    assert _verdict_from(r) == "verified"


def test_verdict_from_metadata_drift_year() -> None:
    r = APIResult(source="arxiv", title="t", authors=["a"], year="2025",
                  title_overlap=0.9, author_match=True, year_diff=5)
    assert _verdict_from(r) == "metadata-drift"


def test_verdict_from_metadata_drift_author() -> None:
    r = APIResult(source="arxiv", title="t", authors=["other"], year="2020",
                  title_overlap=0.9, author_match=False, year_diff=0)
    assert _verdict_from(r) == "metadata-drift"


def test_verdict_from_weak() -> None:
    r = APIResult(source="arxiv", title="t", authors=["a"], year="2020",
                  title_overlap=0.5, author_match=True, year_diff=0)
    assert _verdict_from(r) == "weak-match"


def test_verdict_from_not_found_low_overlap() -> None:
    r = APIResult(source="arxiv", title="t", authors=["a"], year="2020",
                  title_overlap=0.2, author_match=False, year_diff=99)
    assert _verdict_from(r) == "not-found"


def test_verdict_from_none() -> None:
    assert _verdict_from(None) == "not-found"


def test_verify_entry_api_error_when_source_fails_and_no_candidates() -> None:
    # arXiv request failed (None) and S2 returned nothing -> api-error, not
    # a false "not found / likely fabricated".
    e = BibEntry("k", "article", {"title": "Some Real Paper", "author": "X", "year": "2020"})
    with patch("refscan.verify.arxiv_search_metadata", return_value=None), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[]):
        best, others, err = verify_entry(e, sleep=False)
    assert best is None
    assert err == "api-error"


def test_verify_entry_not_found_when_apis_genuinely_empty() -> None:
    # Both sources reachable but returned no matches -> genuine not-found (no error).
    e = BibEntry("k", "article", {"title": "Imaginary Paper", "author": "X", "year": "2020"})
    with patch("refscan.verify.arxiv_search_metadata", return_value=[]), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[]):
        best, others, err = verify_entry(e, sleep=False)
    assert best is None
    assert err is None  # -> _verdict_from(None) == "not-found"


def test_verify_entry_partial_failure_still_yields_candidate() -> None:
    # arXiv failed but S2 returned a strong match -> no error, real verdict.
    e = BibEntry("k", "article", {"title": "Neural Ordinary Differential Equations",
                                   "author": "Chen", "year": "2018"})
    s2_hit = {"title": "Neural Ordinary Differential Equations",
              "authors": ["Chen"], "year": "2018", "arxiv_id": "1806.07366"}
    with patch("refscan.verify.arxiv_search_metadata", return_value=None), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[s2_hit]):
        best, others, err = verify_entry(e, sleep=False)
    assert err is None
    assert best is not None
    assert best.source == "s2"


def test_render_verification_md_minimal() -> None:
    results = [
        VerifyResult(key="good_one", bib_title="Some Title",
                     bib_first_author="Smith", bib_year="2020",
                     bib_pdf_present=True, verdict="verified"),
        VerifyResult(key="bad_one", bib_title="Generic Title",
                     bib_first_author="", bib_year="2024",
                     bib_pdf_present=False, verdict="not-found"),
    ]
    md = render_verification_md("test_paper", results, scan_date="2026-04-24")
    assert "# test_paper — Bib Verification Report" in md
    assert "good_one" in md
    assert "bad_one" in md
    assert "Not found" in md
    assert "Verified" in md
