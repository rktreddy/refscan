"""Tests for text processing primitives."""
from __future__ import annotations

from refscan.textproc import (
    normalize_prose,
    repair_letter_spacing,
    shingles,
    strip_latex,
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
    # Does not merge runs shorter than 4 letters
    assert repair_letter_spacing("a b cat") == "a b cat"


def test_strip_latex_drops_math_environment() -> None:
    src = r"text \begin{align} y &= x \\ z &= w \end{align} more text"
    out = strip_latex(src)
    assert "y" not in out.split()
    assert "more text" in out
