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
    """Rejoin letter-spaced fragments produced by pdftotext.

    Handles **long single-letter runs** like "d i f f e r e n t i a b l e" →
    "differentiable", which appear when pdftotext extracts text rendered with
    aggressive letter-spacing.

    Conservative by design — requires 4+ consecutive single-letter tokens, so
    legitimate prose like "I am here" and math formulas like "a b c" are not
    corrupted.

    For partial-word patterns where each word's first letter is detached
    (e.g. "D IFFERENTIABLE A RCHITECTURE S EARCH" or "A N I MAGE IS W ORTH"),
    use ``title_word_match`` instead — it falls back to substring matching
    against the whitespace-collapsed text, which catches these without
    corruption risk.
    """
    def _join(m: re.Match) -> str:
        return "".join(m.group(0).split())

    return re.sub(r"(?:\b[a-z]\s){3,}[a-z]\b", _join, text)


def collapse_whitespace(text: str) -> str:
    """Return ``text`` with all whitespace removed. Useful for substring matching
    against letter-spaced PDF titles where word boundaries are unreliable."""
    return re.sub(r"\s+", "", text)


def title_word_match(bib_title: str, pdf_text: str,
                     min_word_len: int = 4) -> float:
    """Compute robust title-word overlap between bib title and PDF text.

    Strategy:
      1. Extract significant words (≥ ``min_word_len`` chars) from bib title.
      2. Apply letter-spacing repair to PDF text (handles pdftotext artifacts).
      3. For each bib word, accept a hit if either:
         - the word appears as a token in repaired PDF text, OR
         - the word appears as a substring in the collapsed (no-whitespace)
           PDF text (catches cases like "A N I MAGE" containing "image").

    Returns the fraction of bib title words matched.
    """
    bib_words = set(re.findall(rf"[a-z]{{{min_word_len},}}", bib_title.lower()))
    if not bib_words:
        return 0.0
    pdf_lower = pdf_text.lower()
    repaired = repair_letter_spacing(pdf_lower)
    pdf_words = set(re.findall(rf"[a-z]{{{min_word_len},}}", repaired))
    collapsed = collapse_whitespace(repaired)
    matched = sum(1 for w in bib_words if w in pdf_words or w in collapsed)
    return matched / len(bib_words)


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
