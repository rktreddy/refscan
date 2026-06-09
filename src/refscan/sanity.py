"""Bib hygiene checks — surface common bibliography problems before they
reach reviewers.

Checks performed:

  * Cited but not defined (LaTeX would error)
  * Defined but not cited (bibliography bloat)
  * Duplicate bib keys (BibTeX would error)
  * Likely-duplicate entries (same title, different keys)
  * Missing required fields (title, author, year)
  * Suspicious year values (> current+1 or < 1900)
  * Stub authors (only "and others", no real first author)
"""
from __future__ import annotations

import datetime as _dt
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .bib import BibEntry, cited_keys, parse_bib


@dataclass
class BibIssue:
    """A single bibliography problem."""
    severity: str   # "error" | "warning" | "info"
    category: str   # short identifier (kebab-case)
    key: str        # bib key, or "" for global issues
    message: str    # human-readable description
    extra: dict = field(default_factory=dict)


_REQUIRED_FIELDS = ("title", "author", "year")
_MIN_REASONABLE_YEAR = 1900


def _normalize_title(title: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation. For dup detection."""
    t = re.sub(r"\s+", " ", title.lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", t)


def _parse_bib_with_duplicates(path: Path) -> tuple[list[BibEntry], list[str]]:
    """Like parse_bib() but also collects raw key occurrences (for dup detection).

    Skips ``@comment``/``@string``/``@preamble`` so they don't trigger false
    duplicate-key warnings.
    """
    raw = path.read_text()
    keys_in_order: list[str] = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", raw):
        if m.group(1).lower() in ("comment", "string", "preamble"):
            continue
        keys_in_order.append(m.group(2))
    return parse_bib(path), keys_in_order


def check_bib(bib_path: Path, cite_files: list[Path]) -> list[BibIssue]:
    """Run all sanity checks. Returns a flat list of BibIssue.

    ``cite_files`` is the list of .tex files to scan for ``\\cite`` keys.
    """
    issues: list[BibIssue] = []
    if not bib_path.exists():
        issues.append(BibIssue("error", "bib-missing", "",
                                f"references.bib not found at {bib_path}"))
        return issues

    entries, raw_keys = _parse_bib_with_duplicates(bib_path)
    cited = cited_keys(cite_files)

    # 1. Duplicate keys in the bib file
    dup_keys = [k for k, c in Counter(raw_keys).items() if c > 1]
    for k in dup_keys:
        issues.append(BibIssue(
            "error", "duplicate-key", k,
            f"key `{k}` defined more than once in references.bib",
        ))

    # 2. Cited keys not defined in bib
    defined = {e.key for e in entries}
    undefined_cites = sorted(cited - defined)
    for k in undefined_cites:
        issues.append(BibIssue(
            "error", "undefined-cite", k,
            f"\\cite{{{k}}} appears in paper but key not defined in references.bib",
        ))

    # 3. Defined but not cited
    unused = sorted(defined - cited)
    for k in unused:
        issues.append(BibIssue(
            "warning", "unused-entry", k,
            f"`{k}` defined in references.bib but never cited",
        ))

    # 4. Likely-duplicate entries (same normalized title, different keys)
    title_to_keys: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        nt = _normalize_title(e.title)
        if nt:
            title_to_keys[nt].append(e.key)
    for nt, keys in title_to_keys.items():
        if len(keys) > 1:
            issues.append(BibIssue(
                "warning", "duplicate-title", "",
                f"{len(keys)} entries share the title \"{nt[:60]}…\": {', '.join(keys)}",
                extra={"keys": keys, "normalized_title": nt},
            ))

    # 5. Missing required fields
    # Software references (@misc, @software, @manual, @online) often legitimately
    # lack year/author; downgrade those to warnings.
    soft_types = {"misc", "software", "manual", "online", "techreport"}
    for e in entries:
        is_soft = e.entry_type in soft_types
        for field_name in _REQUIRED_FIELDS:
            value = e.fields.get(field_name, "").strip()
            if not value:
                if field_name == "title":
                    sev = "error"  # title is always required
                elif is_soft:
                    sev = "info"   # author/year often missing for software
                elif field_name == "author":
                    sev = "warning"
                else:
                    sev = "error"
                issues.append(BibIssue(
                    sev, f"missing-{field_name}", e.key,
                    f"`{e.key}` ({e.entry_type}) missing field `{field_name}`",
                ))

    # 6. Suspicious year values
    current = _dt.date.today().year
    for e in entries:
        y = e.year
        if not y:
            continue  # already flagged by missing-year check
        if not y.isdigit():
            issues.append(BibIssue(
                "warning", "year-not-numeric", e.key,
                f"`{e.key}` year `{y}` is not a four-digit number",
            ))
            continue
        yi = int(y)
        if yi < _MIN_REASONABLE_YEAR:
            issues.append(BibIssue(
                "warning", "year-too-old", e.key,
                f"`{e.key}` year {yi} is suspiciously old (< {_MIN_REASONABLE_YEAR})",
            ))
        elif yi > current + 1:
            issues.append(BibIssue(
                "warning", "year-future", e.key,
                f"`{e.key}` year {yi} is in the future "
                f"(current year is {current})",
            ))

    # 7. Stub authors ("and others" with no named author)
    for e in entries:
        a = e.fields.get("author", "").strip()
        if not a:
            continue
        # If author is exactly "others" or "and others" with nothing meaningful
        # before it, that's a placeholder — likely AI-fabricated.
        a_clean = re.sub(r"\s+", " ", a)
        if a_clean.lower() in ("others", "and others"):
            issues.append(BibIssue(
                "warning", "stub-author", e.key,
                f"`{e.key}` author field is just \"{a_clean}\" — no named author",
            ))

    return issues


_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_LABEL = {"error": "🔴 Error", "warning": "🟡 Warning", "info": "ℹ️ Info"}


def summarize(issues: list[BibIssue]) -> dict[str, int]:
    """Count issues by severity."""
    out = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        out[i.severity] = out.get(i.severity, 0) + 1
    return out


def render_sanity_md(paper_label: str, issues: list[BibIssue],
                      total_entries: int = 0, total_cited: int = 0,
                      scan_date: str = "") -> str:
    """Format issues as a markdown report."""
    out = [f"# {paper_label} — Bib Sanity Report\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    counts = summarize(issues)
    out.append(f"_Bib entries: **{total_entries}**  |  Cited keys: **{total_cited}**_\n\n")

    out.append("## Summary\n\n")
    out.append("| Severity | Count |\n|---|---:|\n")
    for sev in ("error", "warning", "info"):
        if counts[sev] or sev in ("error", "warning"):
            out.append(f"| {_SEVERITY_LABEL[sev]} | {counts[sev]} |\n")
    out.append("\n")

    if not issues:
        out.append("✅ **No issues found.** Bib looks healthy.\n")
        return "".join(out)

    # Group by category, ordered by severity then category name
    by_cat: dict[tuple[str, str], list[BibIssue]] = defaultdict(list)
    for i in issues:
        by_cat[(i.severity, i.category)].append(i)
    cats_sorted = sorted(by_cat.keys(), key=lambda x: (_SEVERITY_RANK[x[0]], x[1]))

    for sev, cat in cats_sorted:
        items = by_cat[(sev, cat)]
        out.append(f"---\n\n## {_SEVERITY_LABEL[sev]}: {cat} ({len(items)})\n\n")
        for issue in items:
            if issue.key:
                out.append(f"- `{issue.key}`: {issue.message.split(': ', 1)[-1] if ': ' in issue.message else issue.message}\n")
            else:
                out.append(f"- {issue.message}\n")
        out.append("\n")

    return "".join(out)


def run_sanity(paper_dir: Path, *, bib: str | None = None,
               sections: str | None = None) -> tuple[list[BibIssue], int, int]:
    """Convenience: resolve layout, run checks, return (issues, n_entries, n_cited).

    ``bib``/``sections`` are optional overrides (typically from CLI flags) layered
    over ``refscan.json`` and the default ``paper/...`` layout.
    """
    from .layout import resolve_layout
    layout = resolve_layout(paper_dir, bib=bib, sections=sections)
    issues = check_bib(layout.bib, layout.cite_files)
    n_entries = len(parse_bib(layout.bib)) if layout.bib.exists() else 0
    n_cited = len(cited_keys(layout.cite_files))
    return issues, n_entries, n_cited
