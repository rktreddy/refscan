"""Tests for the combined HTML report renderer + `check --html`."""
from __future__ import annotations

import json
from pathlib import Path

from refscan.cli import main
from refscan.report import render_html_report, render_json_report, render_sarif_report
from refscan.sanity import BibIssue
from refscan.verify import APIResult, VerifyResult

_SCAN = {
    "findings": [{"score": 0.72, "run_len": 11, "bibkey": "doe2020",
                  "section": "intro.tex", "shingle": "a b c",
                  "paper_context": "your prose", "ref_context": "source prose"}],
    "refs_indexed": ["doe2020"], "refs_failed": [],
}


def test_render_minimal_clean() -> None:
    html = render_html_report("my-paper", status="PASS", scan_date="2026-06-09")
    assert html.startswith("<!DOCTYPE html>")
    assert "my-paper" in html
    assert "PASS" in html
    assert html.rstrip().endswith("</html>")


def test_render_escapes_html() -> None:
    issues = [BibIssue("error", "undefined-cite", "k<x>", "uses <script> tag")]
    html = render_html_report("p", status="FAIL", sanity_issues=issues)
    assert "<script>" not in html          # escaped
    assert "&lt;script&gt;" in html


def test_render_includes_findings_and_scores() -> None:
    scan_result = {
        "findings": [{"score": 0.72, "run_len": 11, "bibkey": "doe2020",
                      "section": "intro.tex", "shingle": "a b c",
                      "paper_context": "your prose here", "ref_context": "source prose here"}],
        "refs_indexed": ["doe2020"], "refs_failed": [],
    }
    html = render_html_report("p", status="WARN", scan_result=scan_result)
    assert "0.72" in html
    assert "doe2020" in html
    assert "your prose here" in html and "source prose here" in html


def test_render_flags_retracted_and_not_found() -> None:
    bm = APIResult(source="openalex", title="Bad", authors=["X"], year="2015",
                   doi="10.1/bad", title_overlap=0.9, retracted=True)
    verify_results = [
        VerifyResult(key="bad", bib_title="Bad Paper", bib_first_author="X",
                     bib_year="2015", bib_pdf_present=False, verdict="verified",
                     best_match=bm, retracted=True),
        VerifyResult(key="ghost", bib_title="Ghost Paper", bib_first_author="Y",
                     bib_year="2024", bib_pdf_present=False, verdict="not-found"),
    ]
    html = render_html_report("p", status="FAIL", verify_results=verify_results)
    assert "Retracted papers cited (1)" in html
    assert "Not found (1)" in html
    assert "ghost" in html


def test_json_report_structure() -> None:
    issues = [BibIssue("error", "undefined-cite", "ghost", "ghost not defined")]
    vr = [VerifyResult(key="bad", bib_title="Bad", bib_first_author="X", bib_year="2015",
                       bib_pdf_present=False, verdict="not-found")]
    doc = json.loads(render_json_report("p", version="0.17.0", status="FAIL",
                                        sanity_issues=issues, scan_result=_SCAN,
                                        verify_results=vr))
    assert doc["tool"] == "refscan" and doc["status"] == "FAIL"
    assert doc["sanity"]["errors"] == 1
    assert doc["scan"]["findings"] == 1 and doc["scan"]["top_score"] == 0.72
    assert doc["verify"]["not_found"] == 1
    assert doc["scan"] is not None and doc["verify"]["items"][0]["key"] == "bad"


def test_json_report_null_sections_when_absent() -> None:
    doc = json.loads(render_json_report("p"))  # no scan, no verify
    assert doc["scan"] is None and doc["verify"] is None


def test_sarif_report_valid_2_1_0() -> None:
    issues = [BibIssue("error", "undefined-cite", "ghost", "ghost not defined")]
    vr = [VerifyResult(key="bad", bib_title="Bad", bib_first_author="X", bib_year="2015",
                       bib_pdf_present=False, verdict="not-found")]
    doc = json.loads(render_sarif_report(version="0.17.0", bib_uri="paper/references.bib",
                                         section_uris={"intro.tex": "paper/sections/intro.tex"},
                                         sanity_issues=issues, scan_result=_SCAN,
                                         verify_results=vr))
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "refscan"
    rule_ids = {r["ruleId"] for r in run["results"]}
    assert "sanity/undefined-cite" in rule_ids
    assert "scan/match" in rule_ids
    assert "verify/not-found" in rule_ids
    # scan finding located at the resolved section path
    scan_res = next(r for r in run["results"] if r["ruleId"] == "scan/match")
    uri = scan_res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "paper/sections/intro.tex"
    assert all(r["level"] in ("error", "warning", "note") for r in run["results"])


def test_cli_check_json_and_sarif_write_files(tmp_path: Path) -> None:
    (tmp_path / "references.bib").write_text(
        "@article{k, title={T}, author={A}, year={2020}}\n")
    (tmp_path / "paper.tex").write_text(r"prose \cite{k}")
    main(["check", str(tmp_path), "--json", "--sarif"])
    rep = tmp_path / "literature"
    assert json.loads((rep / "report.json").read_text())["tool"] == "refscan"
    assert json.loads((rep / "report.sarif").read_text())["version"] == "2.1.0"


def test_cli_check_html_writes_file(tmp_path: Path) -> None:
    (tmp_path / "references.bib").write_text(
        "@article{k, title={T}, author={A}, year={2020}}\n")
    (tmp_path / "paper.tex").write_text(r"prose \cite{k}")
    rc = main(["check", str(tmp_path), "--html"])
    report = tmp_path / "literature" / "report.html"
    assert report.exists()
    assert report.read_text().startswith("<!DOCTYPE html>")
    assert rc in (0, 1)  # WARN (no refs) -> 0; never crashes
