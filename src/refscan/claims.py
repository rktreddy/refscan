"""Uncited-claim detection (``refscan claims``).

An offline, heuristic "citation needed" pass: find sentences that make
citation-worthy claims — numbers, attribution phrases, comparatives — but
contain no ``\\cite``. Claims about the paper's *own* results (first person
plus an internal Table/Figure reference or an own-result verb) are
downweighted: contributions don't need citations, claims about the world do.

Advisory by design: heuristic output must never gate CI, so the command
always exits 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .textproc import sentences, strip_latex

_CITE_RE = re.compile(r"\\[cC]ite[a-zA-Z]*\*?(?:\[[^\]]*\])*\s*\{[^}]*\}")
_REF_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|vref)\s*\{[^}]*\}")
_MIN_SENTENCE_WORDS = 6

_SIGNALS: tuple[tuple[str, int, re.Pattern], ...] = (
    ("percentage", 2, re.compile(r"\b\d+(?:\.\d+)?\s?%")),
    ("multiplier", 2, re.compile(
        r"\b\d+(?:\.\d+)?\s?(?:×|x)\b|\b\d+(?:\.\d+)?[- ]?(?:times|fold)\b",
        re.IGNORECASE)),
    ("metric-number", 1, re.compile(
        r"\b(?:accuracy|error|precision|recall|f1|auc|bleu|rouge|perplexity|"
        r"latency|throughput|speedup|mse|rmse)\b[^.]{0,25}?\d", re.IGNORECASE)),
    ("attribution", 2, re.compile(
        r"\b(?:prior work|previous (?:work|studies|research)|"
        r"recent (?:work|studies|research|advances)|"
        r"it (?:has|had) been (?:shown|demonstrated|observed|established|argued)|"
        r"it is (?:well[- ]known|widely (?:known|accepted|believed|used))|"
        r"studies (?:show|have shown|suggest|indicate)|"
        r"researchers have|has been widely|the literature)\b", re.IGNORECASE)),
    ("state-of-the-art", 1, re.compile(r"\bstate[- ]of[- ]the[- ]art\b",
                                       re.IGNORECASE)),
    ("comparative", 1, re.compile(
        r"\b(?:outperforms?|superior to|better than|surpass(?:es)?|"
        r"improv(?:es|ed) (?:upon|over)|faster than|"
        r"more (?:accurate|efficient|robust) than)\b", re.IGNORECASE)),
    ("universal", 1, re.compile(
        r"\b(?:always|never|the first to|the only|the best|"
        r"no (?:prior|existing) (?:work|method|approach))\b", re.IGNORECASE)),
)

_FIRST_PERSON = re.compile(r"\b(?:we|our|us)\b", re.IGNORECASE)
_INTERNAL_REF = re.compile(
    r"\bREFMARK\b|\b(?:Table|Figure|Fig\.|Section|Appendix|Equation|Eq\.|"
    r"Algorithm)\s*~?\s*\d")
_OWN_RESULT = re.compile(
    r"\bwe\s+(?:show|find|observe|achieve|report|demonstrate|obtain|present|"
    r"measure)\b|\bour\s+(?:results|method|approach|experiments|model|"
    r"implementation)\b", re.IGNORECASE)
_OWN_RESULT_PENALTY = 2


@dataclass
class ClaimFinding:
    """One sentence flagged as a possible uncited claim."""

    section: str
    line: int           # 1-based start line of the containing paragraph
    sentence: str
    signals: list[str]
    score: int


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """Split into blank-line paragraphs as (1-based start line, text) pairs."""
    out: list[tuple[int, str]] = []
    start, buf = 0, []
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not buf:
                start = i
            buf.append(line)
        elif buf:
            out.append((start, "\n".join(buf)))
            buf = []
    if buf:
        out.append((start, "\n".join(buf)))
    return out


def _prepare(paragraph: str) -> str:
    """LaTeX paragraph → plain prose with CITEMARK/REFMARK tokens.

    Citation/ref commands become markers before ``strip_latex`` (which would
    otherwise erase them); ``\\%`` is unescaped *after* stripping, since a
    bare ``%`` would read as a comment during the strip.
    """
    t = _CITE_RE.sub(" CITEMARK ", paragraph)
    t = _REF_RE.sub(" REFMARK ", t)
    t = strip_latex(t)
    return t.replace(r"\%", "%")


def _score_sentence(sentence: str) -> tuple[int, list[str]]:
    """(score, matched signal names) for one prose sentence."""
    score = 0
    matched: list[str] = []
    for name, weight, pat in _SIGNALS:
        if pat.search(sentence):
            score += weight
            matched.append(name)
    if _FIRST_PERSON.search(sentence) and (
            _INTERNAL_REF.search(sentence) or _OWN_RESULT.search(sentence)):
        score -= _OWN_RESULT_PENALTY
    return max(score, 0), matched


def scan_text(section: str, text: str, min_score: int = 2) -> list[ClaimFinding]:
    """Find uncited claims in one section's LaTeX source."""
    findings: list[ClaimFinding] = []
    for line, par in _paragraphs(text):
        for sent in sentences(_prepare(par), min_words=_MIN_SENTENCE_WORDS):
            if "CITEMARK" in sent:
                continue
            score, matched = _score_sentence(sent)
            if score >= min_score:
                clean = re.sub(r"\s*\bREFMARK\b\s*", " ", sent).strip()
                findings.append(ClaimFinding(section, line, clean, matched, score))
    return findings


def find_uncited_claims(tex_files: list[Path],
                        min_score: int = 2) -> list[ClaimFinding]:
    """Scan every section file; findings sorted by score desc, then location."""
    findings: list[ClaimFinding] = []
    for f in tex_files:
        findings.extend(scan_text(f.name, f.read_text(errors="ignore"), min_score))
    findings.sort(key=lambda c: (-c.score, c.section, c.line))
    return findings


def render_claims_md(paper_label: str, findings: list[ClaimFinding], *,
                     min_score: int, scan_date: str = "") -> str:
    """Format findings as a markdown report."""
    out = [f"# {paper_label} — Uncited-Claim Report\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Heuristic pass (min score {min_score}); findings are "
               "suggestions, not verdicts — a sentence may be fine uncited "
               "(common knowledge, own results) or covered by a nearby "
               "citation._\n\n")
    if not findings:
        out.append("**No uncited claims found at this threshold.** 🎉\n")
        return "".join(out)
    out.append(f"**{len(findings)} candidate claim(s)** — consider adding a "
               "citation, softening the claim, or ignoring if already "
               "covered:\n\n")
    by_section: dict[str, list[ClaimFinding]] = {}
    for f in findings:
        by_section.setdefault(f.section, []).append(f)
    for section, items in by_section.items():
        out.append(f"## {section}\n\n")
        for f in items:
            out.append(f"- **line {f.line}** (score {f.score}: "
                       f"{', '.join(f.signals)})\n  > {f.sentence}\n")
        out.append("\n")
    return "".join(out)
