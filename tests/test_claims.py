"""Tests for the uncited-claim detector."""
from __future__ import annotations

from pathlib import Path

from refscan.claims import (
    ClaimFinding,
    _paragraphs,
    _prepare,
    _score_sentence,
    find_uncited_claims,
    render_claims_md,
    scan_text,
)


# --- scoring ---------------------------------------------------------------

def test_percentage_scores() -> None:
    score, signals = _score_sentence("The method improves accuracy by 15% on this benchmark.")
    assert score >= 2 and "percentage" in signals


def test_multiplier_scores() -> None:
    score, signals = _score_sentence("This approach is 3x faster than standard solvers today.")
    assert score >= 2 and "multiplier" in signals


def test_attribution_scores() -> None:
    score, signals = _score_sentence(
        "It has been shown that deep networks memorize random labels easily.")
    assert score >= 2 and "attribution" in signals


def test_comparative_alone_below_default_threshold() -> None:
    score, signals = _score_sentence(
        "The proposed encoder outperforms the baseline encoder consistently here.")
    assert "comparative" in signals
    assert score < 2  # a bare comparative shouldn't fire at default min-score


def test_universal_plus_comparative_scores() -> None:
    score, signals = _score_sentence(
        "This is the first to combine both models and outperforms every baseline.")
    assert "universal" in signals and "comparative" in signals
    assert score >= 2


def test_own_result_downweighted() -> None:
    score, _ = _score_sentence(
        "We show in Table 2 that our method improves accuracy by 15% overall.")
    assert score < 2  # first person + internal ref → own result, not a citation gap


def test_first_person_without_internal_ref_not_downweighted() -> None:
    score, signals = _score_sentence(
        "We build on prior work that reported gains of 15% on this task.")
    assert score >= 2  # attribution to others still needs a cite


# --- LaTeX preparation -------------------------------------------------------

def test_prepare_cite_variants_become_marker() -> None:
    for cite in (r"\cite{a}", r"\citep{a,b}", r"\citet[p. 3]{a}", r"\Citet{a}"):
        out = _prepare(f"Prior work has shown this {cite} in many settings.")
        assert "CITEMARK" in out


def test_prepare_unescapes_percent() -> None:
    out = _prepare(r"The error drops by 15\% in all runs.")
    assert "15%" in out.replace(" %", "%")


def test_prepare_ref_becomes_refmark() -> None:
    out = _prepare(r"We show in Table~\ref{tab:main} that it works.")
    assert "REFMARK" in out


def test_cited_sentence_skipped() -> None:
    text = r"Prior work has shown a 15\% improvement \cite{smith2020}."
    findings = scan_text("intro.tex", text, min_score=2)
    assert findings == []


def test_uncited_sentence_found() -> None:
    text = r"Prior work has shown a 15\% improvement on this benchmark task."
    findings = scan_text("intro.tex", text, min_score=2)
    assert len(findings) == 1
    f = findings[0]
    assert f.section == "intro.tex"
    assert "percentage" in f.signals and "attribution" in f.signals


# --- paragraphs & lines ------------------------------------------------------

def test_paragraphs_track_start_lines() -> None:
    text = "First paragraph line one\ncontinues here.\n\n\nSecond paragraph starts.\n"
    pars = _paragraphs(text)
    assert pars[0][0] == 1
    assert pars[1][0] == 5


def test_finding_reports_paragraph_line() -> None:
    text = ("This opening paragraph is perfectly neutral prose here.\n"
            "\n"
            "Studies show that these models fail badly at extrapolation tasks.\n")
    findings = scan_text("s.tex", text, min_score=2)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_min_score_filter() -> None:
    text = "The proposed encoder outperforms the baseline encoder consistently here.\n"
    assert scan_text("s.tex", text, min_score=2) == []
    low = scan_text("s.tex", text, min_score=1)
    assert len(low) == 1


# --- files, render, CLI ------------------------------------------------------

def test_find_uncited_claims_multi_file(tmp_path: Path) -> None:
    a = tmp_path / "a.tex"
    b = tmp_path / "b.tex"
    a.write_text("Studies show that regularization always helps generalization a lot.\n")
    b.write_text("Nothing remarkable is claimed in this perfectly bland sentence.\n")
    findings = find_uncited_claims([a, b], min_score=2)
    assert [f.section for f in findings] == ["a.tex"]


def test_render_claims_md() -> None:
    findings = [ClaimFinding("intro.tex", 12, "Studies show X improves 15%.",
                             ["attribution", "percentage"], 4)]
    md = render_claims_md("mypaper", findings, min_score=2, scan_date="2026-07-09")
    assert "mypaper" in md and "intro.tex" in md
    assert "line 12" in md and "attribution" in md
    assert "Studies show" in md


def test_render_claims_md_empty() -> None:
    md = render_claims_md("mypaper", [], min_score=2, scan_date="")
    assert "no uncited claims" in md.lower() or "0" in md


def test_cli_claims(tmp_path: Path, capsys) -> None:
    from refscan.cli import main
    (tmp_path / "paper" / "sections").mkdir(parents=True)
    (tmp_path / "paper" / "references.bib").write_text("@article{k,\n title={T},\n}\n")
    (tmp_path / "paper" / "sections" / "intro.tex").write_text(
        "Recent studies show a 40\\% failure rate for such systems in practice.\n")
    rc = main(["claims", str(tmp_path)])
    assert rc == 0  # advisory: always 0, even with findings
    out = capsys.readouterr().out
    assert "1" in out
    report = tmp_path / "literature" / "uncited_claims.md"
    assert report.exists()
    assert "40%" in report.read_text()
