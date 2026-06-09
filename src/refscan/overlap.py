"""Cross-paper overlap detection.

For a research program containing multiple papers, detect passages of shared
prose. Useful as a self-plagiarism check.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .textproc import normalize_prose, shingles, strip_latex, tokenize


def _load_paper_text(section_files: list[Path]) -> dict[str, str]:
    return {
        f.name: normalize_prose(strip_latex(f.read_text(errors="ignore")))
        for f in section_files
    }


def detect_overlap(
    paper_sections: dict[str, list[Path]],
    shingle_n: int = 10,
) -> dict:
    """Detect n-gram overlap between every pair of papers.

    ``paper_sections`` maps paper label → list of its section ``.tex`` files.
    Returns a structured dict describing shingles appearing in 2+ papers and
    the maximal runs per paper-pair.
    """
    corpus = {label: _load_paper_text(files) for label, files in paper_sections.items()}

    # Shingle index: shingle → {paper: {section, ...}}
    shingle_index: dict[tuple[str, ...], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for label, sections in corpus.items():
        for sec, prose in sections.items():
            toks = tokenize(prose)
            for sh in shingles(toks, shingle_n):
                shingle_index[sh][label].add(sec)

    cross_paper = {sh: locs for sh, locs in shingle_index.items() if len(locs) >= 2}

    # Extract longest shared runs per pair
    pair_runs: dict[tuple[str, str], list[str]] = {}
    labels = list(paper_sections.keys())
    for i, la in enumerate(labels):
        for lb in labels[i + 1 :]:
            runs = _maximal_runs_between(corpus[la], corpus[lb], shingle_n)
            runs.sort(key=lambda s: len(s.split()), reverse=True)
            if runs:
                pair_runs[(la, lb)] = runs

    return {
        "pair_runs": pair_runs,
        "cross_paper_shingles": cross_paper,
        "shingle_n": shingle_n,
    }


def _maximal_runs_between(
    sections_a: dict[str, str], sections_b: dict[str, str], n: int
) -> list[str]:
    a_toks = tokenize(" ".join(sections_a.values()))
    b_toks = tokenize(" ".join(sections_b.values()))
    if len(a_toks) < n or len(b_toks) < n:
        return []
    b_shingles = {tuple(b_toks[i : i + n]) for i in range(len(b_toks) - n + 1)}
    runs: list[list[str]] = []
    current: list[str] = []
    i = 0
    while i < len(a_toks) - n + 1:
        sh = tuple(a_toks[i : i + n])
        if sh in b_shingles:
            if not current:
                current = list(sh)
                i += n
            else:
                current.append(a_toks[i + n - 1])
                i += 1
        else:
            if current:
                runs.append(current)
                current = []
            i += 1
    if current:
        runs.append(current)
    return [" ".join(r) for r in runs]


def render_overlap_md(result: dict, scan_date: str = "") -> str:
    """Format an overlap scan result as a markdown report."""
    pair_runs = result["pair_runs"]
    out: list[str] = ["# Cross-Paper Overlap Scan\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Shingle size: {result['shingle_n']} consecutive words_\n\n")

    if not pair_runs:
        out.append(f"## No cross-paper overlap at the {result['shingle_n']}-word threshold.\n")
        return "".join(out)

    for (la, lb), runs in sorted(pair_runs.items(), key=lambda x: -sum(len(r.split()) for r in x[1])):
        total_words = sum(len(r.split()) for r in runs)
        out.append(f"## {la} ↔ {lb}  ({len(runs)} runs, {total_words} shared words)\n\n")
        for r in runs[:10]:
            out.append(f"- **{len(r.split())} words**: \"{r}\"\n")
        if len(runs) > 10:
            out.append(f"- …and {len(runs) - 10} more shorter runs\n")
        out.append("\n")
    return "".join(out)
