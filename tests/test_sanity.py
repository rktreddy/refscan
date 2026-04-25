"""Tests for bib sanity checks."""
from __future__ import annotations

from pathlib import Path

import pytest

from refscan.sanity import check_bib, render_sanity_md, summarize


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    """Create a minimal paper layout under tmp_path; return its root."""
    (tmp_path / "paper" / "sections").mkdir(parents=True)
    (tmp_path / "paper" / "main.tex").write_text("input{sections/intro}\n")
    return tmp_path


def _write(paper: Path, bib: str, sections: dict[str, str] | None = None) -> None:
    (paper / "paper" / "references.bib").write_text(bib)
    if sections:
        for name, content in sections.items():
            (paper / "paper" / "sections" / name).write_text(content)


def test_no_issues_clean_bib(paper: Path) -> None:
    _write(paper,
           bib="""@article{Foo2020,
                  title={A Title},
                  author={Smith, Jane},
                  year={2020}
                  }""",
           sections={"intro.tex": r"See \cite{Foo2020}."})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    assert issues == []


def test_undefined_cite_flagged(paper: Path) -> None:
    _write(paper,
           bib="""@article{Foo2020,
                  title={A Title}, author={Smith, Jane}, year={2020}
                  }""",
           sections={"intro.tex": r"See \cite{Foo2020} and \cite{Missing2021}."})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    cats = {i.category for i in issues}
    assert "undefined-cite" in cats
    assert any(i.key == "Missing2021" and i.severity == "error" for i in issues)


def test_unused_entry_flagged(paper: Path) -> None:
    _write(paper,
           bib="""@article{Foo2020, title={t}, author={a}, year={2020}}
                  @article{Bar2021, title={t}, author={a}, year={2021}}""",
           sections={"intro.tex": r"See \cite{Foo2020}."})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    unused = [i for i in issues if i.category == "unused-entry"]
    assert len(unused) == 1
    assert unused[0].key == "Bar2021"
    assert unused[0].severity == "warning"


def test_duplicate_key_flagged(paper: Path) -> None:
    _write(paper,
           bib="""@article{Foo2020, title={t}, author={a}, year={2020}}
                  @article{Foo2020, title={u}, author={b}, year={2020}}""",
           sections={"intro.tex": r"\cite{Foo2020}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    dup = [i for i in issues if i.category == "duplicate-key"]
    assert len(dup) == 1
    assert dup[0].severity == "error"


def test_duplicate_title_flagged(paper: Path) -> None:
    _write(paper,
           bib="""@article{Foo2020, title={Same Title Words Here}, author={a}, year={2020}}
                  @article{Bar2021, title={SAME title words here}, author={b}, year={2021}}""",
           sections={"intro.tex": r"\cite{Foo2020}\cite{Bar2021}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    dup_titles = [i for i in issues if i.category == "duplicate-title"]
    assert len(dup_titles) == 1


def test_missing_required_fields(paper: Path) -> None:
    _write(paper,
           bib="""@article{NoTitle, author={a}, year={2020}}
                  @article{NoAuthor, title={t}, year={2020}}
                  @article{NoYear, title={t}, author={a}}""",
           sections={"intro.tex": r"\cite{NoTitle}\cite{NoAuthor}\cite{NoYear}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    cats = {i.category for i in issues}
    assert "missing-title" in cats
    assert "missing-author" in cats
    assert "missing-year" in cats


def test_year_in_future_warning(paper: Path) -> None:
    _write(paper,
           bib="""@article{Far2099, title={t}, author={a}, year={2099}}""",
           sections={"intro.tex": r"\cite{Far2099}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    assert any(i.category == "year-future" for i in issues)


def test_year_too_old_warning(paper: Path) -> None:
    _write(paper,
           bib="""@article{Old, title={t}, author={a}, year={1850}}""",
           sections={"intro.tex": r"\cite{Old}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    assert any(i.category == "year-too-old" for i in issues)


def test_stub_author_flagged(paper: Path) -> None:
    _write(paper,
           bib="""@article{Stub, title={t}, author={others}, year={2020}}""",
           sections={"intro.tex": r"\cite{Stub}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    assert any(i.category == "stub-author" for i in issues)


def test_summarize_counts(paper: Path) -> None:
    _write(paper,
           bib="""@article{NoTitle, author={a}, year={2020}}""",
           sections={"intro.tex": r"\cite{NoTitle}\cite{Missing}"})
    issues = check_bib(paper / "paper" / "references.bib",
                        paper / "paper" / "sections")
    counts = summarize(issues)
    assert counts["error"] >= 2  # missing-title + undefined-cite


def test_render_sanity_md_clean() -> None:
    md = render_sanity_md("test", [], total_entries=10, total_cited=10,
                            scan_date="2026-04-24")
    assert "No issues found" in md
    assert "test —" in md


def test_render_sanity_md_groups_by_category() -> None:
    from refscan.sanity import BibIssue
    issues = [
        BibIssue("error", "undefined-cite", "Foo", "msg1"),
        BibIssue("warning", "unused-entry", "Bar", "msg2"),
        BibIssue("error", "missing-title", "Baz", "msg3"),
    ]
    md = render_sanity_md("test", issues, total_entries=3, total_cited=2)
    # Errors come first, then warnings; categories sorted alphabetically within severity
    error_pos = md.index("Error")
    warning_pos = md.index("Warning")
    assert error_pos < warning_pos
