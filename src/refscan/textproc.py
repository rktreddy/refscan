"""Text processing: LaTeX strip, Unicode normalization, tokenization, shingle sets."""
from __future__ import annotations

import re
import unicodedata


_ENVS_TO_DROP = (
    "equation", "align", "gather", "table", "tabular", "figure",
    "algorithm", "algorithmic", "lstlisting", "verbatim", "proof",
    "thebibliography",
)
_KEEP_CMD_CONTENT = ("textbf", "textit", "emph", "text", "mathbf", "texttt")
_REF_CMDS = ("ref", "label", "eqref", "autoref", "pageref", "cref")


def strip_latex(text: str) -> str:
    """Reduce LaTeX source to approximately plain prose.

    Drops math, citation commands, labels/refs, common floating environments,
    and unknown backslash commands. Preserves the text content of emphasis
    commands like ``\\textbf{foo}``.
    """
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    text = re.sub(r"\\\[.*?\\\]", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$[^$]*\$", " ", text)
    for env in _ENVS_TO_DROP:
        text = re.sub(
            rf"\\begin{{{env}\*?}}.*?\\end{{{env}\*?}}", " ", text, flags=re.DOTALL
        )
    text = re.sub(r"\\cite[pt]?\*?\{[^}]*\}", " ", text)
    for cmd in _REF_CMDS:
        text = re.sub(rf"\\{cmd}\{{[^}}]*\}}", " ", text)
    for cmd in _KEEP_CMD_CONTENT:
        text = re.sub(rf"\\{cmd}\{{([^}}]*)\}}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_prose(text: str) -> str:
    """Fold Unicode to ASCII, lowercase, strip punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def repair_letter_spacing(text: str) -> str:
    """Rejoin letter-spaced fragments (``d ifferentiable`` → ``differentiable``).

    PDF rendering often sets titles with letter-spacing, which pdftotext
    preserves as ``\\w \\w \\w ...`` runs. This heuristic merges runs of four or
    more consecutive single-letter tokens back into a single word.
    """
    def merge(m: re.Match) -> str:
        return "".join(m.group(0).split())

    # Require at least 4 single-letter tokens in a row to avoid corrupting
    # legitimate words like "a b" in formulas.
    return re.sub(r"(?:\b[a-z]\s){3,}[a-z]\b", merge, text)


def tokenize(text: str) -> list[str]:
    """Split normalized text into tokens. Filters single-char non-alpha tokens."""
    return [t for t in text.split() if len(t) > 1 or t.isalpha()]


def shingles(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    """Return the set of n-grams over ``tokens``."""
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def sentences(text: str, min_words: int = 8) -> list[str]:
    """Split text into sentence strings (min_words filter applied)."""
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sents if len(s.split()) >= min_words]
