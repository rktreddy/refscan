"""Tests for text processing primitives."""
from __future__ import annotations

from refscan.textproc import (
    collapse_whitespace,
    normalize_prose,
    repair_letter_spacing,
    shingles,
    strip_latex,
    title_word_match,
    tokenize,
)


def test_strip_latex_removes_math_and_commands() -> None:
    src = r"""
    We consider $f(x) = x^2$ and note \cite{Foo2020} that
    \textbf{this claim} holds. See Figure~\ref{fig:1}.
    \begin{equation} y = Ax + b \end{equation}
    """
    out = strip_latex(src)
    assert "x^2" not in out
    assert "Figure" in out
    assert "y = Ax + b" not in out
    assert "this claim" in out
    assert "Foo2020" not in out


def test_normalize_lowercases_and_strips_punct() -> None:
    assert normalize_prose("Hello, World!") == "hello world"
    assert normalize_prose("Test-case\u2014dash") == "test-case dash"


def test_normalize_handles_ligatures() -> None:
    assert normalize_prose("ef\ufb01cient") == "efficient"


def test_tokenize_drops_single_nonalpha() -> None:
    assert tokenize("a  1 hello 2b") == ["a", "hello", "2b"]


def test_shingles_basic() -> None:
    toks = ["a", "b", "c", "d", "e"]
    assert shingles(toks, 3) == {("a", "b", "c"), ("b", "c", "d"), ("c", "d", "e")}


def test_shingles_shorter_than_n() -> None:
    assert shingles(["a", "b"], 5) == set()


def test_repair_letter_spacing() -> None:
    assert repair_letter_spacing("d i f f e r e n t i a b l e") == "differentiable"
    # Does not merge runs shorter than 4 letters with no trailing word
    assert repair_letter_spacing("a b cat") == "a b cat"


def test_repair_does_not_break_normal_prose() -> None:
    # Single "I" + "am" + "here" — only one single letter, should NOT merge
    assert repair_letter_spacing("i am here") == "i am here"


def test_repair_does_not_break_short_math() -> None:
    # Math-like "a b c" with trailing word — must NOT merge
    assert repair_letter_spacing("a b cat") == "a b cat"


def test_repair_long_run_with_trailing_partial() -> None:
    # 5+ singles followed by a partial word — long-run pattern triggers
    out = repair_letter_spacing("d i f f e r e n t iable")
    # Pattern catches the long single run, leaving partial word adjacent
    assert "differen" in out  # the long run got merged


def test_collapse_whitespace() -> None:
    assert collapse_whitespace("a n i mage") == "animage"
    assert collapse_whitespace("hello\tworld\n  foo") == "helloworldfoo"


def test_title_word_match_exact() -> None:
    assert title_word_match("Neural Ordinary Differential Equations",
                             "Neural Ordinary Differential Equations") == 1.0


def test_title_word_match_partial() -> None:
    # 3 of 4 significant words present
    score = title_word_match("Neural Ordinary Differential Equations",
                              "Augmented Neural Ordinary Differential")
    assert score == 0.75


def test_title_word_match_letter_spaced_pdf() -> None:
    # bib has normal title; PDF text is letter-spaced
    bib = "An Image is Worth 16x16 Words"
    pdf = "A N I MAGE IS W ORTH 16 X 16 W ORDS Transformers for Image"
    score = title_word_match(bib, pdf)
    # Significant words in bib: "image", "worth", "words"
    # All should match via collapsed-substring fallback
    assert score >= 0.5


def test_title_word_match_no_overlap() -> None:
    score = title_word_match("Foo Bar Baz Quux",
                              "Completely Different Subject Matter")
    assert score == 0.0


def test_title_word_match_empty_bib() -> None:
    assert title_word_match("", "any text") == 0.0


def test_strip_latex_drops_math_environment() -> None:
    src = r"text \begin{align} y &= x \\ z &= w \end{align} more text"
    out = strip_latex(src)
    assert "y" not in out.split()
    assert "more text" in out
