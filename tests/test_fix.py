"""Tests for the bib auto-fix logic (compute_fixes + in-place apply)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from refscan.bib import BibEntry, parse_bib
from refscan.cli import main
from refscan.fix import BibFix, _apply_to_entry, apply_fixes, compute_fixes
from refscan.verify import APIResult, VerifyResult


def _result(key: str, *, title_overlap: float, year: str = "", doi: str = "",
            author_match: bool = True, source: str = "crossref") -> VerifyResult:
    bm = APIResult(source=source, title="t", authors=["a"], year=year, doi=doi,
                   title_overlap=title_overlap, author_match=author_match)
    return VerifyResult(key=key, bib_title="t", bib_first_author="a", bib_year="",
                        bib_pdf_present=False, verdict="metadata-drift", best_match=bm)


# --- compute_fixes --------------------------------------------------------

def test_adds_missing_doi() -> None:
    e = BibEntry("k", "article", {"title": "T", "author": "A", "year": "2020"})
    fixes = compute_fixes([e], {"k": _result("k", title_overlap=0.9, doi="10.1/abc")})
    assert [(f.field, f.new) for f in fixes] == [("doi", "10.1/abc")]


def test_does_not_touch_existing_doi() -> None:
    e = BibEntry("k", "article", {"title": "T", "doi": "10.x/old", "year": "2020"})
    fixes = compute_fixes([e], {"k": _result("k", title_overlap=0.9, doi="10.1/new")})
    assert fixes == []


def test_fixes_drifted_year_when_author_matches() -> None:
    e = BibEntry("k", "article", {"title": "T", "author": "A", "year": "2019"})
    fixes = compute_fixes([e], {"k": _result("k", title_overlap=0.9, year="2020")})
    assert any(f.field == "year" and f.old == "2019" and f.new == "2020" for f in fixes)


def test_skips_year_when_author_does_not_match() -> None:
    e = BibEntry("k", "article", {"title": "T", "author": "A", "year": "2019"})
    r = _result("k", title_overlap=0.9, year="2020", author_match=False)
    fixes = compute_fixes([e], {"k": r})
    assert all(f.field != "year" for f in fixes)


def test_skips_year_fix_from_arxiv_preprint() -> None:
    # arXiv reports the preprint year (often a year before publication) — must
    # NOT drive a year "correction" of a correct conference/journal year.
    e = BibEntry("k", "article", {"title": "LoRA", "author": "Hu", "year": "2022"})
    r = _result("k", title_overlap=0.95, year="2021", source="arxiv")
    fixes = compute_fixes([e], {"k": r})
    assert all(f.field != "year" for f in fixes)


def test_skips_year_fix_from_s2() -> None:
    e = BibEntry("k", "article", {"title": "T", "author": "Hu", "year": "2022"})
    r = _result("k", title_overlap=0.95, year="2021", source="s2")
    fixes = compute_fixes([e], {"k": r})
    assert all(f.field != "year" for f in fixes)


def test_doi_fix_still_allowed_from_arxiv_match() -> None:
    # Year is gated to crossref/openalex, but a DOI is unambiguous from any source.
    e = BibEntry("k", "article", {"title": "T", "author": "Hu", "year": "2022"})
    r = _result("k", title_overlap=0.95, year="2021", doi="10.1/abc", source="arxiv")
    fixes = compute_fixes([e], {"k": r})
    assert [(f.field, f.new) for f in fixes] == [("doi", "10.1/abc")]


def test_ignores_low_confidence_match() -> None:
    e = BibEntry("k", "article", {"title": "T", "author": "A", "year": "2019"})
    fixes = compute_fixes([e], {"k": _result("k", title_overlap=0.5, year="2020",
                                             doi="10.1/abc")})
    assert fixes == []


# --- in-place text surgery ------------------------------------------------

def test_apply_inserts_doi_and_updates_year(tmp_path: Path) -> None:
    text = "@article{key,\n  author = {Smith, J.},\n  year = {2019}\n}\n"
    out = _apply_to_entry(text, "key", [
        BibFix("key", "doi", "", "10.1/abc", "crossref", "add"),
        BibFix("key", "year", "2019", "2020", "crossref", "drift"),
    ])
    bib = tmp_path / "refs.bib"
    bib.write_text(out)
    e = parse_bib(bib)[0]
    assert e.doi == "10.1/abc"
    assert e.year == "2020"
    assert "Smith, J." in out  # untouched field preserved


def test_apply_preserves_other_entries(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{a, title={A}, author={X}, year={2019}}\n"
        "@article{b, title={B}, author={Y}, year={2021}}\n")
    n = apply_fixes(bib, [BibFix("a", "year", "2019", "2020", "crossref", "drift")])
    assert n == 1
    entries = {e.key: e for e in parse_bib(bib)}
    assert entries["a"].year == "2020"
    assert entries["b"].year == "2021"  # other entry untouched


# --- cli `fix` (preview is read-only; --apply writes + backs up) ----------

def _drift_paper(tmp_path: Path) -> tuple[Path, VerifyResult]:
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "references.bib").write_text(
        "@article{k, title={Deep Residual Learning}, author={He, K}, year={2015}}\n")
    bm = APIResult(source="crossref", title="Deep Residual Learning",
                   authors=["Kaiming He"], year="2016", doi="10.1109/CVPR.2016.90",
                   title_overlap=0.95, author_match=True)
    r = VerifyResult(key="k", bib_title="Deep Residual Learning", bib_first_author="He",
                     bib_year="2015", bib_pdf_present=False, verdict="metadata-drift",
                     best_match=bm)
    return tmp_path, r


def test_cli_fix_preview_does_not_modify(tmp_path: Path) -> None:
    paper, r = _drift_paper(tmp_path)
    before = (paper / "paper" / "references.bib").read_text()
    with patch("refscan.cli.verify_paper", return_value=[r]):
        rc = main(["fix", str(paper)])  # no --apply
    assert rc == 0
    assert (paper / "paper" / "references.bib").read_text() == before
    assert not (paper / "paper" / "references.bib.bak").exists()


def test_cli_fix_apply_writes_and_backs_up(tmp_path: Path) -> None:
    paper, r = _drift_paper(tmp_path)
    with patch("refscan.cli.verify_paper", return_value=[r]):
        rc = main(["fix", str(paper), "--apply"])
    assert rc == 0
    e = {x.key: x for x in parse_bib(paper / "paper" / "references.bib")}["k"]
    assert e.year == "2016"
    assert e.doi == "10.1109/CVPR.2016.90"
    assert (paper / "paper" / "references.bib.bak").exists()


# --- preprint upgrades ----------------------------------------------------

def _preprint_result(key: str) -> VerifyResult:
    pm = APIResult(source="crossref", title="t", authors=["a"], year="2018",
                   doi="10.5555/nips.2017", venue="NeurIPS",
                   title_overlap=0.9, author_match=True)
    bm = APIResult(source="arxiv", title="t", authors=["a"], year="2017",
                   doi="10.48550/arXiv.1706.03762", title_overlap=0.95,
                   author_match=True)
    return VerifyResult(key=key, bib_title="t", bib_first_author="a",
                        bib_year="2017", bib_pdf_present=False,
                        verdict="verified", best_match=bm, published_match=pm)


def _preprint_bib_entry(key: str = "k", entry_type: str = "misc") -> BibEntry:
    return BibEntry(key, entry_type, {
        "title": "T", "author": "A", "year": "2017",
        "eprint": "1706.03762", "archiveprefix": "arXiv",
        "doi": "10.48550/arXiv.1706.03762",
    })


def test_upgrade_off_by_default_no_upgrade_fixes() -> None:
    e = _preprint_bib_entry()
    fixes = compute_fixes([e], {"k": _preprint_result("k")})
    assert all(f.field not in ("journal", "entry-type") for f in fixes)


def test_upgrade_emits_doi_journal_year_type() -> None:
    e = _preprint_bib_entry()
    fixes = compute_fixes([e], {"k": _preprint_result("k")},
                          upgrade_preprints=True)
    by_field = {f.field: f for f in fixes}
    assert by_field["doi"].new == "10.5555/nips.2017"
    assert by_field["doi"].old == "10.48550/arXiv.1706.03762"
    assert by_field["journal"].new == "NeurIPS"
    assert by_field["year"].new == "2018"
    assert by_field["entry-type"].old == "misc"
    assert by_field["entry-type"].new == "article"


def test_upgrade_supersedes_standard_doi_fix() -> None:
    # entry with no DOI: standard logic would add best_match's arXiv DOI,
    # the upgrade must win with the published DOI.
    e = BibEntry("k", "misc", {"title": "T", "author": "A", "year": "2017",
                               "eprint": "1706.03762", "archiveprefix": "arXiv"})
    fixes = compute_fixes([e], {"k": _preprint_result("k")},
                          upgrade_preprints=True)
    dois = [f for f in fixes if f.field == "doi"]
    assert len(dois) == 1 and dois[0].new == "10.5555/nips.2017"


def test_upgrade_keeps_non_misc_entry_type() -> None:
    e = _preprint_bib_entry(entry_type="article")
    fixes = compute_fixes([e], {"k": _preprint_result("k")},
                          upgrade_preprints=True)
    assert all(f.field != "entry-type" for f in fixes)


def test_apply_entry_type_rewrite(tmp_path: Path) -> None:
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@misc{k,\n"
        "  title = {T},\n"
        "  author = {A},\n"
        "  year = {2017},\n"
        "  eprint = {1706.03762},\n"
        "}\n\n"
        "@misc{other,\n  title = {Other},\n}\n")
    fixes = [BibFix("k", "entry-type", "misc", "article", "crossref", "upgrade"),
             BibFix("k", "journal", "", "NeurIPS", "crossref", "venue"),
             BibFix("k", "year", "2017", "2018", "crossref", "pub year")]
    apply_fixes(bib, fixes)
    text = bib.read_text()
    assert "@article{k," in text
    assert "@misc{other," in text            # untouched neighbor
    assert "journal = {NeurIPS}" in text
    assert "year = {2018}" in text
    assert "eprint = {1706.03762}" in text   # eprint preserved
