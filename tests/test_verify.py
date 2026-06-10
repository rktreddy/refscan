"""Tests for verify module — verdict logic, scoring, markdown rendering.

Network calls are not exercised; verify_entry/verify_paper are skipped in
favor of direct testing of the pure scoring + verdict functions.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from refscan.bib import BibEntry
from refscan.verify import (
    APIResult,
    VerifyResult,
    _author_in,
    _cache_matches,
    _score_candidate,
    _title_overlap,
    _verdict_from,
    render_verification_md,
    verify_entry,
    verify_paper,
)


def _make_paper(tmp_path: Path, bib: str) -> Path:
    paper_dir = tmp_path / "p"
    (paper_dir / "paper").mkdir(parents=True)
    (paper_dir / "literature").mkdir(parents=True)
    (paper_dir / "paper" / "references.bib").write_text(bib)
    return paper_dir


def _seed_cache(paper_dir: Path, key: str, **fields) -> None:
    rec = {
        "key": key, "bib_title": "", "bib_first_author": "", "bib_year": "",
        "bib_pdf_present": False, "verdict": "verified",
        "best_match": None, "other_matches": [],
    }
    rec.update(fields)
    (paper_dir / "literature" / "verify_cache.json").write_text(json.dumps({key: rec}))


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
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[]), \
         patch("refscan.verify.openalex_search_metadata", return_value=[]), \
         patch("refscan.verify.crossref_search_metadata", return_value=[]):
        best, others, err = verify_entry(e, sleep=False)
    assert best is None
    assert err == "api-error"


def test_verify_entry_not_found_when_apis_genuinely_empty() -> None:
    # Both sources reachable but returned no matches -> genuine not-found (no error).
    e = BibEntry("k", "article", {"title": "Imaginary Paper", "author": "X", "year": "2020"})
    with patch("refscan.verify.arxiv_search_metadata", return_value=[]), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[]), \
         patch("refscan.verify.openalex_search_metadata", return_value=[]), \
         patch("refscan.verify.crossref_search_metadata", return_value=[]):
        best, others, err = verify_entry(e, sleep=False)
    assert best is None
    assert err is None  # -> _verdict_from(None) == "not-found"


def test_verify_entry_uses_openalex_when_arxiv_s2_empty() -> None:
    # A real non-arXiv paper: arXiv + S2 return nothing, OpenAlex confirms it.
    e = BibEntry("k", "article", {"title": "Attention Is All You Need",
                                   "author": "Vaswani", "year": "2017"})
    oa = {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani"],
          "year": "2017", "arxiv_id": "", "doi": "10.5555/3295222.3295349"}
    with patch("refscan.verify.arxiv_search_metadata", return_value=[]), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[]), \
         patch("refscan.verify.openalex_search_metadata", return_value=[oa]), \
         patch("refscan.verify.crossref_search_metadata", return_value=[]):
        best, others, err = verify_entry(e, sleep=False)
    assert err is None
    assert best is not None
    assert best.source == "openalex"
    assert best.doi == "10.5555/3295222.3295349"


def test_score_candidate_carries_retracted_flag() -> None:
    e = BibEntry("k", "article", {"title": "Bad Paper", "author": "X", "year": "2015"})
    cand = {"title": "Bad Paper", "authors": ["X"], "year": "2015", "retracted": True}
    r = _score_candidate(e, cand, "openalex")
    assert r.retracted is True


def test_verify_paper_flags_retracted_match(tmp_path) -> None:
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "references.bib").write_text(
        "@article{k, title={Bad Paper}, author={X}, year={2015}}\n")
    (tmp_path / "literature").mkdir()
    bm = APIResult(source="openalex", title="Bad Paper", authors=["X"], year="2015",
                   title_overlap=0.95, author_match=True, retracted=True)
    with patch("refscan.verify.verify_entry", return_value=(bm, [], None)):
        results = verify_paper(tmp_path, use_s2=False, progress=False)
    assert results[0].retracted is True


def test_render_flags_retracted_section() -> None:
    bm = APIResult(source="openalex", title="Bad Paper", authors=["X"], year="2015",
                   doi="10.1/bad", title_overlap=0.95, author_match=True, retracted=True)
    results = [VerifyResult(key="bad", bib_title="Bad Paper", bib_first_author="X",
                            bib_year="2015", bib_pdf_present=False, verdict="verified",
                            best_match=bm, retracted=True)]
    md = render_verification_md("p", results, scan_date="2026-06-09")
    assert "Retracted papers (1)" in md
    assert "`bad`" in md


def test_verify_entry_uses_crossref_for_journal_paper() -> None:
    e = BibEntry("k", "article", {"title": "Deep Residual Learning",
                                   "author": "He", "year": "2016"})
    cr = {"title": "Deep Residual Learning", "authors": ["Kaiming He"],
          "year": "2016", "arxiv_id": "", "doi": "10.1109/CVPR.2016.90"}
    with patch("refscan.verify.arxiv_search_metadata", return_value=[]), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[]), \
         patch("refscan.verify.openalex_search_metadata", return_value=[]), \
         patch("refscan.verify.crossref_search_metadata", return_value=[cr]):
        best, others, err = verify_entry(e, sleep=False)
    assert err is None
    assert best is not None
    assert best.source == "crossref"


def test_verify_entry_partial_failure_still_yields_candidate() -> None:
    # arXiv failed but S2 returned a strong match -> no error, real verdict.
    e = BibEntry("k", "article", {"title": "Neural Ordinary Differential Equations",
                                   "author": "Chen", "year": "2018"})
    s2_hit = {"title": "Neural Ordinary Differential Equations",
              "authors": ["Chen"], "year": "2018", "arxiv_id": "1806.07366"}
    with patch("refscan.verify.arxiv_search_metadata", return_value=None), \
         patch("refscan.verify.semantic_scholar_search_metadata", return_value=[s2_hit]), \
         patch("refscan.verify.openalex_search_metadata", return_value=[]), \
         patch("refscan.verify.crossref_search_metadata", return_value=[]):
        best, others, err = verify_entry(e, sleep=False)
    assert err is None
    assert best is not None
    assert best.source == "s2"


def test_cache_matches() -> None:
    e = BibEntry("k", "article", {"title": "T", "author": "Smith, J.", "year": "2020"})
    same = VerifyResult(key="k", bib_title="T", bib_first_author="Smith",
                        bib_year="2020", bib_pdf_present=False, verdict="verified")
    drifted = VerifyResult(key="k", bib_title="Different", bib_first_author="Smith",
                           bib_year="2020", bib_pdf_present=False, verdict="verified")
    assert _cache_matches(same, e)
    assert not _cache_matches(drifted, e)


def test_verify_paper_cache_hit_when_metadata_matches(tmp_path: Path) -> None:
    paper_dir = _make_paper(
        tmp_path, "@article{k1, title={Correct Title}, author={Smith, J.}, year={2020}}\n")
    _seed_cache(paper_dir, "k1", bib_title="Correct Title",
                bib_first_author="Smith", bib_year="2020", verdict="verified")
    with patch("refscan.verify.verify_entry") as ve:
        results = verify_paper(paper_dir, use_s2=False, progress=False)
    ve.assert_not_called()                  # served from cache
    assert results[0].verdict == "verified"


def test_verify_paper_cache_invalidated_on_title_change(tmp_path: Path) -> None:
    # Bib title was corrected since the cache was written -> must re-query.
    paper_dir = _make_paper(
        tmp_path, "@article{k1, title={New Correct Title}, author={Smith, J.}, year={2020}}\n")
    _seed_cache(paper_dir, "k1", bib_title="Old Wrong Title",
                bib_first_author="Smith", bib_year="2020", verdict="verified")
    with patch("refscan.verify.verify_entry", return_value=(None, [], None)) as ve:
        results = verify_paper(paper_dir, use_s2=False, progress=False)
    ve.assert_called_once()                 # stale cache -> re-queried
    assert results[0].bib_title == "New Correct Title"
    assert results[0].verdict == "not-found"


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
