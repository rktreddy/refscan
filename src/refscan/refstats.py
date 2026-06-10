"""Reference-balance statistics — recency, age, and self-citation.

These are *presentation* signals, not integrity ones: reviewers often note a
bibliography that skews old or leans heavily on self-citation. This surfaces
those before submission. Bib-only, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bib import BibEntry

_MIN_YEAR = 1900


@dataclass
class RefStats:
    total: int
    with_year: int
    year_min: int | None
    year_max: int | None
    median_year: int | None
    pct_last_5: float          # share of dated entries within the last 5 years
    pct_last_10: float
    current_year: int
    self_citations: int | None = None      # None when no author given
    self_citation_pct: float | None = None
    by_year: dict[int, int] = field(default_factory=dict)


def compute_refstats(entries: list[BibEntry], current_year: int,
                     author_surnames: list[str] | None = None) -> RefStats:
    """Compute reference-balance stats. ``author_surnames`` enables self-citation."""
    years = sorted(int(e.year) for e in entries
                   if e.year.isdigit() and _MIN_YEAR <= int(e.year) <= current_year + 1)
    n = len(years)
    by_year: dict[int, int] = {}
    for y in years:
        by_year[y] = by_year.get(y, 0) + 1

    if n:
        ymin, ymax = years[0], years[-1]
        median = (years[(n - 1) // 2] + years[n // 2]) // 2
        last5 = sum(1 for y in years if y >= current_year - 4)
        last10 = sum(1 for y in years if y >= current_year - 9)
        pct5, pct10 = 100.0 * last5 / n, 100.0 * last10 / n
    else:
        ymin = ymax = median = None
        pct5 = pct10 = 0.0

    self_c: int | None = None
    self_pct: float | None = None
    surs = [s.lower() for s in (author_surnames or []) if s]
    if surs:
        self_c = sum(1 for e in entries
                     if any(s in e.fields.get("author", "").lower() for s in surs))
        self_pct = 100.0 * self_c / len(entries) if entries else 0.0

    return RefStats(total=len(entries), with_year=n, year_min=ymin, year_max=ymax,
                    median_year=median, pct_last_5=pct5, pct_last_10=pct10,
                    current_year=current_year, self_citations=self_c,
                    self_citation_pct=self_pct, by_year=by_year)


def render_refstats_md(paper_label: str, s: RefStats, scan_date: str = "") -> str:
    """Format reference-balance stats as a markdown report."""
    out = [f"# {paper_label} — Reference Balance\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Total references: **{s.total}**  ·  with a usable year: "
               f"**{s.with_year}**_\n\n")

    if not s.with_year:
        out.append("No dated references to analyze.\n")
        return "".join(out)

    out.append("## Recency\n\n")
    out.append(f"- Year range: **{s.year_min}–{s.year_max}**  ·  median year: "
               f"**{s.median_year}**\n")
    out.append(f"- Within last 5 years ({s.current_year - 4}+): **{s.pct_last_5:.0f}%**\n")
    out.append(f"- Within last 10 years ({s.current_year - 9}+): **{s.pct_last_10:.0f}%**\n")
    if s.pct_last_5 < 30:
        out.append("- ⚠️ Fewer than a third of references are recent — reviewers may "
                   "read the bibliography as dated.\n")
    out.append("\n")

    if s.self_citations is not None:
        out.append("## Self-citation\n\n")
        out.append(f"- **{s.self_citations}** of {s.total} entries "
                   f"(**{s.self_citation_pct:.0f}%**) match the given author name(s).\n")
        if s.self_citation_pct is not None and s.self_citation_pct > 25:
            out.append("- ⚠️ High self-citation share — a common reviewer complaint.\n")
        out.append("\n")

    out.append("## By year\n\n")
    peak = max(s.by_year.values())
    for y in sorted(s.by_year, reverse=True):
        bar = "█" * max(1, round(10 * s.by_year[y] / peak))
        out.append(f"- `{y}`  {bar} {s.by_year[y]}\n")
    return "".join(out)
