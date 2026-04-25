"""Tests for scan runs and finding generation."""
from __future__ import annotations

from refscan.scan import find_runs, is_generic_shingle


def test_find_runs_exact_match() -> None:
    paper = "the quick brown fox jumps over the lazy dog".split()
    ref_shingles = {("quick", "brown", "fox"), ("brown", "fox", "jumps")}
    runs = find_runs(paper, ref_shingles, n=3, min_run=3)
    assert runs == [(1, 4)]  # starts at "quick", length 4 tokens


def test_find_runs_no_match() -> None:
    paper = "something entirely different content here".split()
    ref_shingles = {("quick", "brown", "fox")}
    assert find_runs(paper, ref_shingles, n=3, min_run=3) == []


def test_find_runs_respects_min_run() -> None:
    paper = "a b c d e".split()
    ref_shingles = {("a", "b", "c")}  # Single matching shingle, length 3
    assert find_runs(paper, ref_shingles, n=3, min_run=5) == []
    assert find_runs(paper, ref_shingles, n=3, min_run=3) == [(0, 3)]


def test_is_generic_shingle_flags_boilerplate() -> None:
    assert is_generic_shingle("we propose that this method")
    assert is_generic_shingle("in the paper we")
    assert is_generic_shingle("the the the of and or")


def test_is_generic_shingle_accepts_technical() -> None:
    assert not is_generic_shingle("adjoint method for neural ordinary differential")
    assert not is_generic_shingle("wasserstein uncertainty ball radius epsilon")
