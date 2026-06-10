"""Tests for the semantic scan core (with a fake, dependency-free embedder)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from refscan import semantic
from refscan.cli import main
from refscan.semantic import (
    available,
    render_semantic_md,
    semantic_findings,
    split_sentences,
)

_DIM = 256


def _bow(texts):
    """Deterministic hashing embedder into a fixed space (normalized), no ML deps.

    Fixed dimensions across calls — mirrors a real sentence embedder, so the
    paper-batch and ref-batch vectors are comparable.
    """
    out = []
    for t in texts:
        v = [0.0] * _DIM
        for w in t.lower().split():
            b = int(hashlib.md5(w.encode()).hexdigest(), 16) % _DIM
            v[b] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / norm for x in v])
    return out


def test_available_returns_bool() -> None:
    assert isinstance(available(), bool)


def test_split_sentences_min_words() -> None:
    s = split_sentences("Short one. This sentence has more than six words in it. Hi.",
                        min_words=6)
    assert len(s) == 1
    assert s[0].startswith("This sentence")


def test_findings_flag_close_pair() -> None:
    paper = [("intro.tex", "the adjoint method computes gradients efficiently here")]
    refs = [("doe2020", "the adjoint method computes gradients efficiently here"),
            ("foo", "completely unrelated sentence about cooking pasta tonight")]
    f = semantic_findings(paper, refs, _bow, threshold=0.8)
    assert len(f) == 1
    assert f[0]["bibkey"] == "doe2020"
    assert f[0]["similarity"] >= 0.8


def test_findings_skip_below_threshold() -> None:
    paper = [("s", "alpha beta gamma delta epsilon zeta")]
    refs = [("r", "completely different words entirely unrelated nonsense")]
    assert semantic_findings(paper, refs, _bow, threshold=0.5) == []


def test_findings_empty_inputs() -> None:
    assert semantic_findings([], [("r", "x")], _bow) == []
    assert semantic_findings([("s", "x")], [], _bow) == []


def test_render_semantic_md() -> None:
    findings = [{"section": "intro.tex", "bibkey": "doe2020", "similarity": 0.91,
                 "paper_sentence": "p", "ref_sentence": "r"}]
    md = render_semantic_md("paper", findings, threshold=0.75, scan_date="2026-06-09")
    assert "Semantic Scan — paper" in md
    assert "doe2020" in md and "0.91" in md


def test_cli_semscan_errors_without_extra(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "references.bib").write_text(
        "@article{k, title={T}, author={A}, year={2020}}\n")
    (tmp_path / "paper.tex").write_text("prose with several words here please thanks")
    (tmp_path / "literature" / "refs").mkdir(parents=True)
    monkeypatch.setattr(semantic, "available", lambda: False)
    rc = main(["semscan", str(tmp_path)])
    assert rc == 1  # graceful: tells the user to install the extra
