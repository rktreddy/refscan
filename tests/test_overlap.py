"""Tests for cross-paper overlap detection (file-list based)."""
from __future__ import annotations

from pathlib import Path

from refscan.overlap import detect_overlap

_SHARED = ("the adjoint method computes gradients of neural ordinary "
           "differential equations efficiently without storing intermediate states")


def test_detect_overlap_finds_shared_run(tmp_path: Path) -> None:
    a = tmp_path / "a.tex"
    b = tmp_path / "b.tex"
    a.write_text("Intro alpha beta. " + _SHARED + " Then unique gamma delta.")
    b.write_text("Different opening words here. " + _SHARED + " And distinct epsilon.")
    res = detect_overlap({"A": [a], "B": [b]}, shingle_n=6)
    assert res["pair_runs"]
    assert ("A", "B") in res["pair_runs"]


def test_detect_overlap_none_when_disjoint(tmp_path: Path) -> None:
    a = tmp_path / "a.tex"
    b = tmp_path / "b.tex"
    a.write_text("alpha beta gamma delta epsilon zeta eta theta iota kappa")
    b.write_text("one two three four five six seven eight nine ten eleven")
    res = detect_overlap({"A": [a], "B": [b]}, shingle_n=6)
    assert not res["pair_runs"]


def test_detect_overlap_multiple_files_per_paper(tmp_path: Path) -> None:
    a1 = tmp_path / "a1.tex"
    a2 = tmp_path / "a2.tex"
    b = tmp_path / "b.tex"
    a1.write_text("Some intro prose that is entirely unique to paper a.")
    a2.write_text(_SHARED)
    b.write_text("Lead in. " + _SHARED)
    res = detect_overlap({"A": [a1, a2], "B": [b]}, shingle_n=6)
    assert ("A", "B") in res["pair_runs"]
