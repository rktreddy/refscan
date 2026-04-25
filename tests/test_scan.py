"""Tests for scan runs and finding generation."""
from __future__ import annotations

from refscan.scan import (
    confidence_score,
    find_runs,
    is_generic_shingle,
    render_findings_terminal,
)


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


def test_confidence_score_rewards_length() -> None:
    short = confidence_score("foo bar baz qux quux corge", 6, 1)
    longer = confidence_score("foo bar baz qux quux corge grault waldo plugh xyzzy", 10, 1)
    assert longer > short


def test_confidence_score_penalizes_stopwords() -> None:
    # 6 words, mostly content words
    technical = confidence_score("adjoint method neural ordinary differential equation", 6, 1)
    # 6 words, dominated by stopwords (the, of, in, the, of, and)
    boilerplate = confidence_score("the of in the of and", 6, 1)
    assert technical > boilerplate


def test_confidence_score_penalizes_common_phrases() -> None:
    # Same shingle/length, but appearing in many references is less concerning
    rare = confidence_score("adjoint method neural ordinary differential equation", 6, 1)
    common = confidence_score("adjoint method neural ordinary differential equation", 6, 10)
    assert rare > common


def test_confidence_score_in_unit_interval() -> None:
    # Even with extreme parameters, score stays bounded in [0, 1]
    s = confidence_score("a b c d e f g h i j k l m n", 14, 1)
    assert 0.0 < s <= 1.0
    # All-stopword + many refs collapses to 0 (intentional)
    s_low = confidence_score("the of in the of and", 6, 50)
    assert 0.0 <= s_low <= 1.0


def test_confidence_score_pure_stopwords_zero_signal() -> None:
    # All-stopwords shingle should have very low score (non_stop_frac == 0)
    s = confidence_score("the of and", 3, 1)
    assert s == 0.0


def test_render_findings_terminal_no_findings() -> None:
    result = {"findings": [], "refs_indexed": ["a", "b", "c"], "refs_failed": []}
    out = render_findings_terminal(result)
    assert "no matches" in out
    assert "refs indexed: 3" in out


def test_render_findings_terminal_with_findings() -> None:
    result = {
        "findings": [
            {"score": 0.42, "run_len": 8, "bibkey": "Foo2020",
             "section": "intro.tex",
             "shingle": "neural ordinary differential equation adjoint method here"},
            {"score": 0.35, "run_len": 6, "bibkey": "Bar2021",
             "section": "method.tex",
             "shingle": "the upper bound of theorem"},
        ],
        "refs_indexed": ["Foo2020", "Bar2021"],
        "refs_failed": [],
    }
    out = render_findings_terminal(result, top_n=2)
    assert "findings: 2" in out
    assert "Foo2020" in out
    assert "Bar2021" in out
    assert "0.42" in out


def test_render_findings_terminal_top_n_caps() -> None:
    result = {
        "findings": [
            {"score": 0.5 - i * 0.05, "run_len": 6, "bibkey": f"K{i}",
             "section": "s.tex", "shingle": "shingle text " * 3}
            for i in range(10)
        ],
        "refs_indexed": [f"K{i}" for i in range(10)],
        "refs_failed": [],
    }
    out = render_findings_terminal(result, top_n=3)
    # Should show 3 numbered entries
    for n in (1, 2, 3):
        assert f"{n}." in out
    # Should not show 4th
    assert "4." not in out
