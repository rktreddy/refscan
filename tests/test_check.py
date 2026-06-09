"""Tests for the one-shot `refscan check` command (verdict + exit codes)."""
from __future__ import annotations

from pathlib import Path

from refscan.cli import main


def _paper(tmp_path: Path, bib: str, body: str = r"Some prose \cite{k}.") -> Path:
    # Flat, no-config layout — exercises auto-detection too.
    (tmp_path / "references.bib").write_text(bib)
    (tmp_path / "paper.tex").write_text(body)
    return tmp_path


_GOOD_BIB = "@article{k, title={A Title}, author={Smith, Jane}, year={2020}}\n"


def test_check_pass_clean_paper(tmp_path: Path, capsys) -> None:
    paper = _paper(tmp_path, _GOOD_BIB)
    rc = main(["check", str(paper)])  # no refs -> scan skipped (WARN), no verify
    out = capsys.readouterr().out
    assert "refscan check:" in out
    assert "(auto-detected)" in out  # bib + sections discovered
    # No refs downloaded yet -> scan skipped -> WARN, but exit 0 (not FAIL)
    assert rc == 0
    assert "WARN" in out


def test_check_fail_on_sanity_error(tmp_path: Path) -> None:
    # Undefined citation -> sanity error -> FAIL -> exit 1.
    paper = _paper(tmp_path, _GOOD_BIB, body=r"\cite{k}\cite{ghost}")
    rc = main(["check", str(paper)])
    assert rc == 1


def test_check_writes_reports(tmp_path: Path) -> None:
    paper = _paper(tmp_path, _GOOD_BIB)
    main(["check", str(paper)])
    assert (paper / "literature" / "sanity_report.md").exists()


def test_check_missing_bib_errors(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text(r"\cite{k}")  # no .bib anywhere
    rc = main(["check", str(tmp_path)])
    assert rc == 1


def test_check_scan_runs_when_refs_present(tmp_path: Path, capsys) -> None:
    paper = _paper(tmp_path, _GOOD_BIB)
    # Provide a (small but valid-length) cached text so a "ref" indexes without pdftotext.
    refs = paper / "literature" / "refs"
    cache = paper / "literature" / "pdf_text_cache"
    refs.mkdir(parents=True)
    cache.mkdir(parents=True)
    (refs / "k.pdf").write_bytes(b"%PDF-1.4 " + b"x" * 6000)
    # Pre-seed the extraction cache (newer than the pdf) so scan skips pdftotext.
    (cache / "k.txt").write_text("unrelated reference text " * 100)
    rc = main(["check", str(paper)])
    out = capsys.readouterr().out
    assert "scan:" in out
    assert "refs indexed" in out
    assert rc == 0
