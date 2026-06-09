"""Per-paper reference tracking markdown generator."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .bib import BibEntry, parse_bib, ref_pdf_path

# Optional per-paper config file. Lives at the paper-dir root so a paper can
# supply its own title/key heuristics without baking them into the package.
CONFIG_FILENAME = "refscan.json"


@dataclass(frozen=True)
class TrackConfig:
    """Per-paper categorization heuristics, all optional and lowercase-matched.

    With an empty config (the default), categorization relies only on general
    BibTeX signals — entry type (``@book``/``@inbook`` → skip-book, ``@software``
    → skip-software) and publication year. These marker lists let a specific
    paper augment that with its own substring/key heuristics:

      * ``book_title_markers``    — title substrings → ``skip-book``
      * ``software_keys``         — exact bib keys  → ``skip-software``
      * ``software_title_markers``— title substrings → ``skip-software``
      * ``suspect_title_markers`` — title substrings on 2015+ entries →
        ``verify-exists``. This is a coarse static heuristic; ``refscan verify``
        is the robust way to detect fabricated references.
    """
    book_title_markers: tuple[str, ...] = ()
    software_keys: frozenset[str] = field(default_factory=frozenset)
    software_title_markers: tuple[str, ...] = ()
    suspect_title_markers: tuple[str, ...] = ()


DEFAULT_CONFIG = TrackConfig()

_CONFIG_TEMPLATE = {
    "_comment": (
        "Optional per-paper heuristics for `refscan track`/`verify`. All lists "
        "are lowercase substring/key matches and may be left empty. `refscan "
        "verify` is the robust way to detect fabricated references; "
        "suspect_title_markers is only a coarse offline pre-filter."
    ),
    "book_title_markers": [],
    "software_keys": [],
    "software_title_markers": [],
    "suspect_title_markers": [],
}


def write_config_template(paper_dir: Path) -> Path | None:
    """Write a commented ``refscan.json`` template if none exists.

    Returns the path if written, or ``None`` if a config already exists.
    """
    path = paper_dir / CONFIG_FILENAME
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_CONFIG_TEMPLATE, indent=2) + "\n")
    return path


def _lower_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(str(v).lower() for v in values)


def load_config(paper_dir: Path) -> TrackConfig:
    """Load ``<paper_dir>/refscan.json`` if present, else return empty defaults.

    A missing or malformed file is treated as "no extra heuristics" rather than
    an error — categorization still works from general BibTeX signals.
    """
    path = paper_dir / CONFIG_FILENAME
    if not path.exists():
        return DEFAULT_CONFIG
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG
    if not isinstance(data, dict):
        return DEFAULT_CONFIG
    return TrackConfig(
        book_title_markers=_lower_tuple(data.get("book_title_markers")),
        software_keys=frozenset(_lower_tuple(data.get("software_keys"))),
        software_title_markers=_lower_tuple(data.get("software_title_markers")),
        suspect_title_markers=_lower_tuple(data.get("suspect_title_markers")),
    )


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


def categorize(entry: BibEntry, pdf_present: bool,
               config: TrackConfig = DEFAULT_CONFIG) -> str:
    """Assign a category bucket for a bib entry.

    Uses general BibTeX signals (entry type, year) plus any paper-specific
    title/key markers supplied via ``config``.
    """
    if pdf_present:
        return "downloaded"
    t = entry.title.lower()
    k = entry.key.lower()
    et = entry.entry_type

    if et == "software" or k in config.software_keys \
            or any(m in t for m in config.software_title_markers):
        return "skip-software"
    if et in ("book", "inbook") or any(m in t for m in config.book_title_markers):
        return "skip-book"
    if entry.year.isdigit() and int(entry.year) < 2000:
        return "pre-arxiv"
    if entry.year.isdigit() and int(entry.year) >= 2015:
        if any(m in t for m in config.suspect_title_markers):
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
    config: TrackConfig | None = None,
) -> tuple[Path, dict[str, int]]:
    """Write a `reference_tracking.md` for one paper. Return (path, counts).

    ``config`` defaults to whatever ``<paper_dir>/refscan.json`` provides (empty
    if absent). Pass an explicit ``TrackConfig`` to override.
    """
    bib_path = bib_path or (paper_dir / "paper" / "references.bib")
    refs_dir = refs_dir or (paper_dir / "literature" / "refs")
    output_path = output_path or (paper_dir / "literature" / "reference_tracking.md")
    if config is None:
        config = load_config(paper_dir)

    entries = parse_bib(bib_path)
    bucketed: dict[str, list[BibEntry]] = {b: [] for b in _BUCKET_ORDER}
    for e in entries:
        p = ref_pdf_path(refs_dir, e.key)
        pdf_present = bool(p and p.exists())
        bucketed[categorize(e, pdf_present, config)].append(e)

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
