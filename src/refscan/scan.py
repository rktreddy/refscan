"""Paper-vs-references plagiarism scan via shingle matching."""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

from .textproc import (
    normalize_prose,
    repair_letter_spacing,
    shingles,
    strip_latex,
    tokenize,
)

DEFAULT_SHINGLE_N = 6
DEFAULT_MIN_RUN = 6
DEFAULT_MAX_RUNS_PER_REF = 15

_GENERIC_PATTERNS = [
    re.compile(r"^we (propose|show|demonstrate|find|present|introduce|consider|study|prove|observe) (that |a |an |the )", re.IGNORECASE),
    re.compile(r"^(in|from|to|for|with|on|at|by) (the|a|this|these|our|their) ", re.IGNORECASE),
    re.compile(r"^(the|a|an) (paper|work|method|approach|algorithm|model|result|problem|task) ", re.IGNORECASE),
    re.compile(r"figure \d", re.IGNORECASE),
    re.compile(r"table \d", re.IGNORECASE),
    re.compile(r"section \d", re.IGNORECASE),
]

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "in", "for", "is", "on", "that", "by",
    "with", "as", "at", "we", "this", "be", "are", "it", "from", "or", "can",
    "which", "has", "been", "not", "our", "have", "its", "where", "these",
    "such", "also", "but", "more",
}


def is_generic_shingle(text: str) -> bool:
    """True if the shingle is academic boilerplate or too stopword-dense."""
    for pat in _GENERIC_PATTERNS:
        if pat.search(text):
            return True
    words = text.split()
    non_stop = [w for w in words if w not in _STOPWORDS]
    return len(non_stop) < 3


def extract_pdf_text(pdf_path: Path, cache_dir: Path, repair: bool = True) -> str:
    """Extract PDF text via ``pdftotext``, caching by mtime. Empty on failure."""
    cache = cache_dir / (pdf_path.stem + ".txt")
    if cache.exists() and cache.stat().st_mtime >= pdf_path.stat().st_mtime:
        text = cache.read_text(errors="ignore")
    else:
        cache.parent.mkdir(parents=True, exist_ok=True)
        text = _run_pdftotext(pdf_path, cache)
    if repair and text:
        text = repair_letter_spacing(text.lower())
    return text


def _run_pdftotext(pdf_path: Path, cache: Path) -> str:
    for args in (
        ["pdftotext", "-layout", "-nopgbrk", str(pdf_path), str(cache)],
        ["pdftotext", "-nopgbrk", str(pdf_path), str(cache)],
    ):
        try:
            subprocess.run(args, check=True, capture_output=True, timeout=60)
            if cache.exists():
                return cache.read_text(errors="ignore")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return ""


def find_runs(
    paper_tokens: list[str],
    ref_shingles: set[tuple[str, ...]],
    n: int,
    min_run: int,
) -> list[tuple[int, int]]:
    """Locate maximal runs in ``paper_tokens`` whose n-grams appear in ``ref_shingles``.

    Returns list of (start_index, run_length_in_tokens).
    """
    if len(paper_tokens) < n:
        return []
    runs: list[tuple[int, int]] = []
    i = 0
    while i <= len(paper_tokens) - n:
        if tuple(paper_tokens[i : i + n]) not in ref_shingles:
            i += 1
            continue
        run_start = i
        run_end = i + n
        while run_end - n + 1 <= len(paper_tokens) - n:
            nxt = tuple(paper_tokens[run_end - n + 1 : run_end + 1])
            if nxt in ref_shingles:
                run_end += 1
            else:
                break
        if run_end - run_start >= min_run:
            runs.append((run_start, run_end - run_start))
        i = run_end + 1
    return runs


def _index_reference_pdfs(
    refs_dir: Path, cache_dir: Path, shingle_n: int
) -> tuple[dict[str, set[tuple[str, ...]]], dict[str, list[str]], list[tuple[str, str]]]:
    ref_indices: dict[str, set[tuple[str, ...]]] = {}
    ref_tokens: dict[str, list[str]] = {}
    failed: list[tuple[str, str]] = []
    for pdf in sorted(refs_dir.glob("*.pdf")):
        bibkey = pdf.stem
        raw = extract_pdf_text(pdf, cache_dir)
        if not raw or len(raw) < 500:
            failed.append((bibkey, "extraction empty or too short"))
            continue
        toks = tokenize(normalize_prose(raw))
        if len(toks) < shingle_n:
            failed.append((bibkey, "text too short after tokenizing"))
            continue
        ref_indices[bibkey] = shingles(toks, shingle_n)
        ref_tokens[bibkey] = toks
    return ref_indices, ref_tokens, failed


def confidence_score(shingle_text: str, run_len: int, num_refs_with_phrase: int) -> float:
    """Compute a 0–1 confidence that a finding is concerning rather than noise.

    Three factors:
      - **Length**: longer runs are stronger signal. Maps run_len→[0.5, 1.0]
        via a saturating curve (8w gets ~0.7, 12w gets ~0.85, 20w → 1.0).
      - **Non-stopword density**: shingles dominated by stopwords are weaker.
        Computed as 1 - (stopword_count / total_words).
      - **Phrase rarity**: phrases shared by many references are likely
        technical terminology, not concerning paraphrase. Computed as
        1 / sqrt(num_refs_with_phrase).

    Returns score in (0, 1]; higher = more concerning.
    """
    words = shingle_text.split()
    n = len(words) or 1
    stop_n = sum(1 for w in words if w in _STOPWORDS)
    non_stop_frac = 1.0 - (stop_n / n)
    # Length factor: 1 - exp(-run_len / 10) gives ~0.55 at 8w, ~0.70 at 12w, ~0.86 at 20w
    import math
    length_factor = 1.0 - math.exp(-run_len / 10.0)
    rarity = 1.0 / math.sqrt(max(1, num_refs_with_phrase))
    return length_factor * non_stop_frac * rarity


def scan(
    sections_dir: Path,
    refs_dir: Path,
    cache_dir: Path | None = None,
    shingle_n: int = DEFAULT_SHINGLE_N,
    min_run: int = DEFAULT_MIN_RUN,
    filter_generic: bool = True,
) -> dict:
    """Run a plagiarism scan. Return a dict with findings and metadata."""
    cache_dir = cache_dir or (refs_dir.parent / "pdf_text_cache")
    ref_indices, ref_tokens, failed = _index_reference_pdfs(refs_dir, cache_dir, shingle_n)

    findings = []
    for sec_file in sorted(sections_dir.glob("*.tex")):
        raw = sec_file.read_text(errors="ignore")
        paper_toks = tokenize(normalize_prose(strip_latex(raw)))
        if len(paper_toks) < shingle_n:
            continue
        for bibkey, ref_shingles in ref_indices.items():
            for run_start, run_len in find_runs(paper_toks, ref_shingles, shingle_n, min_run):
                sh_text = " ".join(paper_toks[run_start : run_start + run_len])
                if filter_generic and is_generic_shingle(sh_text):
                    continue
                ctx_lo = max(0, run_start - 5)
                ctx_hi = min(len(paper_toks), run_start + run_len + 5)
                paper_ctx = " ".join(paper_toks[ctx_lo:ctx_hi])
                ref_ctx = _reference_context(
                    ref_tokens[bibkey],
                    paper_toks[run_start : run_start + run_len],
                    window=5,
                )
                findings.append({
                    "section": sec_file.name,
                    "bibkey": bibkey,
                    "run_len": run_len,
                    "shingle": sh_text,
                    "paper_context": paper_ctx,
                    "ref_context": ref_ctx,
                })

    # Compute phrase rarity: how many distinct refs contain each shingle text?
    # We use a normalized prefix (first 8 tokens) as the phrase key so near-
    # duplicate runs with shared prefixes get treated as the same phrase.
    phrase_freq: dict[str, set[str]] = {}
    for f in findings:
        prefix = " ".join(f["shingle"].split()[:8])
        phrase_freq.setdefault(prefix, set()).add(f["bibkey"])

    # Annotate each finding with its confidence score.
    for f in findings:
        prefix = " ".join(f["shingle"].split()[:8])
        f["score"] = confidence_score(f["shingle"], f["run_len"], len(phrase_freq[prefix]))

    # Sort by score descending; tie-break by run_len then section name.
    findings.sort(key=lambda f: (-f["score"], -f["run_len"], f["section"]))
    # Deduplicate adjacent overlapping shingles
    seen = set()
    dedup = []
    for f in findings:
        key = (f["section"], f["bibkey"], f["shingle"][:40])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(f)

    return {
        "findings": dedup,
        "refs_indexed": list(ref_indices.keys()),
        "refs_failed": failed,
        "shingle_n": shingle_n,
        "min_run": min_run,
    }


def render_findings_terminal(result: dict, top_n: int = 5,
                                width: int = 80) -> str:
    """Compact terminal summary: one line per top-N finding. No markdown."""
    findings = result["findings"]
    n_refs = len(result["refs_indexed"])
    n_failed = len(result["refs_failed"])
    lines = [
        f"  refs indexed: {n_refs}  |  failed: {n_failed}  |  findings: {len(findings)}",
    ]
    if not findings:
        lines.append("  ✓ no matches above noise threshold")
        return "\n".join(lines)
    lines.append(f"  top {min(top_n, len(findings))} by confidence:")
    for i, f in enumerate(findings[:top_n], 1):
        # Truncate shingle to fit on one line
        sh = f["shingle"]
        max_sh = max(20, width - 50)
        if len(sh) > max_sh:
            sh = sh[:max_sh - 1] + "…"
        lines.append(f"    {i}. {f['score']:.2f} | {f['run_len']:>2}w | "
                     f"{f['bibkey'][:18]:<18} | {f['section'][:18]:<18} | {sh}")
    return "\n".join(lines)


def _reference_context(ref_toks: list[str], run: list[str], window: int = 5) -> str:
    run_tuple = tuple(run)
    n = len(run_tuple)
    for j in range(len(ref_toks) - n + 1):
        if tuple(ref_toks[j : j + n]) == run_tuple:
            lo = max(0, j - window)
            hi = min(len(ref_toks), j + n + window)
            return " ".join(ref_toks[lo:hi])
    return ""


def render_findings_md(
    paper_label: str,
    result: dict,
    scan_date: str = "",
    max_runs_per_ref: int = DEFAULT_MAX_RUNS_PER_REF,
) -> str:
    """Format a scan result as a markdown report."""
    findings = result["findings"]
    out: list[str] = [f"# Plagiarism Scan — {paper_label}\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Shingle size: {result['shingle_n']} consecutive words_\n")
    out.append(f"_Minimum run length reported: {result['min_run']} words_\n\n")
    out.append(f"**References indexed:** {len(result['refs_indexed'])}\n")
    out.append(f"**References failed:** {len(result['refs_failed'])}\n")
    out.append(f"**Raw findings (after generic-filter):** {len(findings)}\n\n")

    out.append("## How to read this report\n\n")
    out.append(
        "Each finding shows a sequence of consecutive words shared between "
        "the paper and a cited reference. Not every finding is plagiarism:\n\n"
        "- **Technical terminology matches** are expected and benign.\n"
        "- **Quoted theorem statements or definitions** with proper attribution are fine.\n"
        "- **Author/venue names and citation clusters** are noise.\n"
        "- **Concern-worthy**: a 10+ word run of paraphrase that tracks the source's sentence structure closely.\n\n"
        "Each finding is annotated with a **confidence score** (0.0–1.0) "
        "combining run length, non-stopword density, and phrase rarity across "
        "your reference corpus. Higher = more likely a real concern. Findings "
        "are sorted by score; the **Top concerning matches** section surfaces "
        "the highest-score finding overall so you can review it first.\n\n"
    )

    if result["refs_failed"]:
        out.append("## ⚠️ Reference PDFs that failed to process\n\n")
        out.append("| Key | Reason |\n|-----|--------|\n")
        for k, r in result["refs_failed"]:
            out.append(f"| `{k}` | {r} |\n")
        out.append("\n")

    if not findings:
        out.append("## ✅ No matches found above the noise threshold.\n\n")
        return "".join(out)

    # Top concerning matches across all references (top 10 or fewer)
    top_n = min(10, len(findings))
    out.append(f"## 🔝 Top {top_n} concerning matches (highest confidence)\n\n")
    out.append("| # | Score | Words | Reference | Section | Shingle (first 80 chars) |\n")
    out.append("|---|------:|------:|-----------|---------|--------------------------|\n")
    for i, f in enumerate(findings[:top_n], 1):
        sh_short = f['shingle'][:80] + ("…" if len(f['shingle']) > 80 else "")
        out.append(f"| {i} | {f['score']:.2f} | {f['run_len']} | "
                   f"`{f['bibkey']}` | `{f['section']}` | {sh_short} |\n")
    out.append("\n")

    by_ref: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_ref[f["bibkey"]].append(f)
    # Sort references by max score (not max run_len) — more useful prioritization.
    ref_order = sorted(by_ref.keys(), key=lambda k: -max(f["score"] for f in by_ref[k]))
    out.append("## All findings, grouped by cited reference\n\n")
    out.append("Ranked by max confidence score within each reference.\n\n")
    for bibkey in ref_order:
        fs = sorted(by_ref[bibkey], key=lambda x: -x["score"])
        out.append(f"### `{bibkey}` — {len(fs)} matches, "
                   f"max score = {fs[0]['score']:.2f}, "
                   f"longest = {max(f['run_len'] for f in fs)} words\n\n")
        for f in fs[:max_runs_per_ref]:
            out.append(f"**score {f['score']:.2f}** | **{f['run_len']} words** "
                       f"(section `{f['section']}`):\n\n")
            out.append(f"- Paper: …{f['paper_context']}…\n")
            out.append(f"- Ref:   …{f['ref_context']}…\n\n")
        if len(fs) > max_runs_per_ref:
            out.append(f"_…and {len(fs) - max_runs_per_ref} shorter runs omitted._\n\n")
    return "".join(out)
