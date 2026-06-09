"""End-to-end tests that a flat (non-`paper/`) layout works via config + flags."""
from __future__ import annotations

import json
from pathlib import Path

from refscan.cli import main
from refscan.sanity import run_sanity


def _flat_paper(tmp_path: Path, with_config: bool = True) -> Path:
    (tmp_path / "references.bib").write_text(
        "@article{neural_ode, title={Neural ODEs}, author={Chen, R}, year={2018}}\n")
    (tmp_path / "paper.tex").write_text(
        r"We study neural ODEs \cite{neural_ode} in depth here.")
    if with_config:
        (tmp_path / "refscan.json").write_text(
            json.dumps({"bib": "references.bib", "sections": "paper.tex"}))
    return tmp_path


def test_run_sanity_flat_layout_via_config(tmp_path: Path) -> None:
    paper = _flat_paper(tmp_path)
    issues, n_entries, n_cited = run_sanity(paper)
    assert n_entries == 1
    assert n_cited == 1
    assert all(i.category != "undefined-cite" for i in issues)


def test_run_sanity_flat_layout_via_flags(tmp_path: Path) -> None:
    paper = _flat_paper(tmp_path, with_config=False)  # no refscan.json
    issues, n_entries, n_cited = run_sanity(
        paper, bib="references.bib", sections="paper.tex")
    assert (n_entries, n_cited) == (1, 1)


def test_cli_init_then_scan_flat_layout(tmp_path: Path) -> None:
    paper = _flat_paper(tmp_path)
    assert main(["init", str(paper)]) == 0
    # init scaffolds literature/refs; scan must resolve paper.tex (not paper/sections)
    assert main(["scan", str(paper)]) == 0
    assert (paper / "literature" / "plagiarism_findings.md").exists()


def test_cli_sanity_with_flags_no_config(tmp_path: Path) -> None:
    paper = _flat_paper(tmp_path, with_config=False)
    rc = main(["sanity-stats", str(paper), "--bib", "references.bib",
               "--sections", "paper.tex"])
    assert rc == 0  # all cites defined, no errors -> exit 0
    assert (paper / "literature" / "sanity_report.md").exists()


def test_cli_scan_errors_when_no_sections(tmp_path: Path) -> None:
    # Default layout, but no paper/sections and no config -> clear error, exit 1
    (tmp_path / "literature" / "refs").mkdir(parents=True)
    assert main(["scan", str(tmp_path)]) == 1


def test_default_layout_still_works(tmp_path: Path) -> None:
    # The conventional paper/{references.bib,sections} layout is unaffected.
    (tmp_path / "paper" / "sections").mkdir(parents=True)
    (tmp_path / "paper" / "references.bib").write_text(
        "@article{k, title={T}, author={A}, year={2020}}\n")
    (tmp_path / "paper" / "sections" / "intro.tex").write_text(r"\cite{k}")
    issues, n_entries, n_cited = run_sanity(tmp_path)
    assert (n_entries, n_cited) == (1, 1)
