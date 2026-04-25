"""Per-paper reference tracking markdown generator."""
from __future__ import annotations

import re
from pathlib import Path

from .bib import BibEntry, parse_bib

# Generic-title markers indicating likely-fabricated references
_GENERIC_FABRICATED_MARKERS = (
    "advances in neuromorphic",
    "coupled oscillator networks for",
    "coupling strength effects in oscillator",
    "memristor-based analog computing",
    "hardware-friendly algorithm design for",
    "role of analog memory in",
    "sound and heat revolutions",
    "information-theoretic analysis of generalization in neural networks",
    "learning dynamical systems from trajectories",
    "silicon photonic neural networks for efficient",
)

_BOOK_TITLE_MARKERS = (
    "nonlinear dynamics and chaos",
    "elements of information theory",
    "solving ordinary differential",
    "numerical methods for ordinary",
    "qualitative theory of differential",
    "analog integrated circuit design",
    "op amps for",
    "switched-capacitor",
    "linear programming",
    "perceptrons: an introduction",
)

_SOFTWARE_KEYS = {"jax", "xla", "pytorch", "tensorrt", "aihwkit"}
_SOFTWARE_TITLE_MARKERS = ("tensorrt", "python+numpy")

_BUCKET_HEADINGS = {
    "verify-exists": "⚠️ Verify existence first (may be fabricated)",
    "fetchable": "🔽 Fetchable — please download",
    "pre-arxiv": "📜 Pre-arXiv (optional)",
    "skip-book": "📚 Books & textbooks — skip",
    "skip-software": "💻 Software docs — skip",
    "downloaded": "✅ Downloaded — ready to scan",
}

_BUCKET_INSTRUCTIONS = {
    "verify-exists": (
        "Search Google Scholar before fetching. "
        "If the paper does not exist, **remove the citation from `paper/references.bib`**."
    ),
    "fetchable": (
        "Download and save as `literature/refs/{KEY}.pdf` "
        "(filename must exactly match the bib key)."
    ),
    "pre-arxiv": (
        "Google Scholar often has author-hosted PDFs. "
        "Plagiarism-scan value is moderate."
    ),
    "skip-book": (
        "Not worth scanning — textbook prose is rarely the source of "
        "reviewer-flaggable paraphrase."
    ),
    "skip-software": "No academic prose to plagiarize.",
    "downloaded": "Already in `literature/refs/`. Nothing to do.",
}

_BUCKET_ORDER = (
    "verify-exists",
    "fetchable",
    "pre-arxiv",
    "skip-book",
    "skip-software",
    "downloaded",
)


def categorize(entry: BibEntry, pdf_present: bool) -> str:
    """Assign a category bucket for a bib entry."""
    if pdf_present:
        return "downloaded"
    t = entry.title.lower()
    k = entry.key.lower()
    et = entry.entry_type

    if k in _SOFTWARE_KEYS or any(m in t for m in _SOFTWARE_TITLE_MARKERS):
        return "skip-software"
    if et in ("book", "inbook") or any(m in t for m in _BOOK_TITLE_MARKERS):
        return "skip-book"
    if entry.year.isdigit() and int(entry.year) < 2000:
        return "pre-arxiv"
    if entry.year.isdigit() and int(entry.year) >= 2015:
        if any(m in t for m in _GENERIC_FABRICATED_MARKERS):
            return "verify-exists"
    return "fetchable"


def _best_source(entry: BibEntry) -> str:
    t = entry.title.lower()
    if "nature" in t:
        return "author site / arXiv preprint"
    if entry.entry_type == "inproceedings":
        return "venue proceedings / author site"
    return "Google Scholar (PDF link)"


def generate_tracking_md(
    paper_dir: Path,
    paper_label: str,
    bib_path: Path | None = None,
    refs_dir: Path | None = None,
    output_path: Path | None = None,
    scan_date: str = "",
) -> tuple[Path, dict[str, int]]:
    """Write a `reference_tracking.md` for one paper. Return (path, counts)."""
    bib_path = bib_path or (paper_dir / "paper" / "references.bib")
    refs_dir = refs_dir or (paper_dir / "literature" / "refs")
    output_path = output_path or (paper_dir / "literature" / "reference_tracking.md")

    entries = parse_bib(bib_path)
    bucketed: dict[str, list[BibEntry]] = {b: [] for b in _BUCKET_ORDER}
    for e in entries:
        pdf_present = (refs_dir / f"{e.key}.pdf").exists()
        bucketed[categorize(e, pdf_present)].append(e)

    out: list[str] = [f"# {paper_label} — Reference PDF Tracking\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Total references: **{len(entries)}**_\n\n")

    out.append("## Summary\n\n| Status | Count | Action |\n|---|---|---|\n")
    summary_rows = [
        ("downloaded", "✅ Downloaded", "ready to scan"),
        ("fetchable", "🔽 Fetchable", "**please download**"),
        ("verify-exists", "⚠️ Verify existence", "**check Google Scholar**"),
        ("pre-arxiv", "📜 Pre-arXiv", "optional"),
        ("skip-book", "📚 Books", "skip"),
        ("skip-software", "💻 Software", "skip"),
    ]
    for bucket, label, action in summary_rows:
        n = len(bucketed[bucket])
        if n > 0 or bucket in ("downloaded", "fetchable"):
            out.append(f"| {label} | {n} | {action} |\n")
    out.append("\n")
    out.append(
        "**Drop downloaded PDFs at:** `literature/refs/{KEY}.pdf` "
        "(filename must exactly match the bib key — case-sensitive).\n\n"
    )

    for bucket in _BUCKET_ORDER:
        items = bucketed[bucket]
        if not items:
            continue
        out.append(f"---\n\n## {_BUCKET_HEADINGS[bucket]} ({len(items)})\n\n")
        out.append(f"{_BUCKET_INSTRUCTIONS[bucket]}\n\n")
        if bucket == "verify-exists":
            out.append("| # | Key | Title | Year | First Author |\n")
            out.append("|---|-----|-------|------|---------------|\n")
            for i, e in enumerate(items, 1):
                ts = (e.title[:90] + "…") if len(e.title) > 90 else e.title
                out.append(f"| {i} | `{e.key}` | {ts} | {e.year} | {e.first_author} |\n")
        elif bucket == "fetchable":
            out.append("| # | Key | Title | Year | First Author | Best source |\n")
            out.append("|---|-----|-------|------|---------------|-------------|\n")
            for i, e in enumerate(
                sorted(items, key=lambda x: (x.first_author or "zz", x.year or "0000")), 1
            ):
                ts = (e.title[:85] + "…") if len(e.title) > 85 else e.title
                out.append(
                    f"| {i} | `{e.key}` | {ts} | {e.year} | {e.first_author} | {_best_source(e)} |\n"
                )
        else:
            out.append("| Key | Title | Year |\n|-----|-------|------|\n")
            for e in sorted(items, key=lambda x: (x.first_author or "zz", x.year or "0000")):
                ts = (e.title[:80] + "…") if len(e.title) > 80 else e.title
                out.append(f"| `{e.key}` | {ts} | {e.year} |\n")
        out.append("\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(out))
    return output_path, {b: len(bucketed[b]) for b in _BUCKET_ORDER}
