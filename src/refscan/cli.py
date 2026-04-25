"""Command-line entry point for refscan."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from . import __version__
from .bib import parse_bib
from .fetch import ARXIV_DELAY_S, fetch_entry
from .overlap import detect_overlap, render_overlap_md
from .scan import DEFAULT_MIN_RUN, DEFAULT_SHINGLE_N, render_findings_md, scan
from .track import generate_tracking_md


def _today() -> str:
    return dt.date.today().isoformat()


def _paper_label(paper_dir: Path) -> str:
    return paper_dir.name


def cmd_init(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    lit = paper_dir / "literature"
    (lit / "refs").mkdir(parents=True, exist_ok=True)
    (lit / "pdf_text_cache").mkdir(parents=True, exist_ok=True)
    bib = paper_dir / "paper" / "references.bib"
    if not bib.exists():
        print(f"warning: no bib file found at {bib}", file=sys.stderr)
    # Write an initial tracking file
    generate_tracking_md(paper_dir, _paper_label(paper_dir), scan_date=_today())
    print(f"initialized {lit}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    bib = Path(args.bib) if args.bib else paper_dir / "paper" / "references.bib"
    refs_dir = paper_dir / "literature" / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)

    entries = parse_bib(bib)
    n_before = sum(1 for e in entries if (refs_dir / f"{e.key}.pdf").exists())
    downloaded = 0
    for idx, e in enumerate(entries, 1):
        dest = refs_dir / f"{e.key}.pdf"
        if dest.exists():
            continue
        print(f"[{idx}/{len(entries)}] {e.key}: {e.title[:70]}...")
        ok, src = fetch_entry(e, dest, try_s2=not args.no_s2)
        if ok:
            downloaded += 1
            print(f"  ✓ {src}")
        else:
            print("  ✗ not found")
    print(f"\nbefore: {n_before} / {len(entries)}  |  newly downloaded: {downloaded}  |  "
          f"still missing: {len(entries) - n_before - downloaded}")
    # Refresh tracking file to reflect new state
    generate_tracking_md(paper_dir, _paper_label(paper_dir), scan_date=_today())
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    path, counts = generate_tracking_md(
        paper_dir, _paper_label(paper_dir), scan_date=_today()
    )
    print(f"wrote {path}")
    for bucket, n in counts.items():
        print(f"  {bucket}: {n}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    sections = paper_dir / "paper" / "sections"
    refs = paper_dir / "literature" / "refs"
    if not sections.is_dir() or not refs.is_dir():
        print(f"error: expected {sections} and {refs} to exist", file=sys.stderr)
        return 1
    result = scan(
        sections_dir=sections,
        refs_dir=refs,
        shingle_n=args.shingle_n,
        min_run=args.min_run,
        filter_generic=not args.no_filter,
    )
    report = render_findings_md(_paper_label(paper_dir), result, scan_date=_today())
    out_path = Path(args.out) if args.out else paper_dir / "literature" / "plagiarism_findings.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"refs indexed: {len(result['refs_indexed'])}  |  "
          f"failed: {len(result['refs_failed'])}  |  "
          f"findings: {len(result['findings'])}")
    print(f"wrote {out_path}")
    return 0


def cmd_overlap(args: argparse.Namespace) -> int:
    paper_dirs = [Path(p).resolve() for p in args.paper_dirs]
    sections = {p.name: p / "paper" / "sections" for p in paper_dirs}
    for label, d in sections.items():
        if not d.is_dir():
            print(f"warning: {label} missing sections dir at {d}", file=sys.stderr)
    result = detect_overlap(sections, shingle_n=args.shingle_n)
    report = render_overlap_md(result, scan_date=_today())
    out_path = Path(args.out) if args.out else Path.cwd() / "overlap_report.md"
    out_path.write_text(report)
    print(f"paper pairs with overlap: {len(result['pair_runs'])}")
    print(f"wrote {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="refscan",
        description="Reference collection and plagiarism scanning for research papers.",
    )
    p.add_argument("--version", action="version", version=f"refscan {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="scaffold literature/ directories and initial tracking file")
    pi.add_argument("paper_dir", help="paper directory containing paper/references.bib")
    pi.set_defaults(func=cmd_init)

    pf = sub.add_parser("fetch", help="download reference PDFs via arXiv and Semantic Scholar")
    pf.add_argument("paper_dir")
    pf.add_argument("--bib", help="override path to references.bib")
    pf.add_argument("--no-s2", action="store_true",
                    help="skip Semantic Scholar fallback (arXiv only)")
    pf.set_defaults(func=cmd_fetch)

    pt = sub.add_parser("track", help="regenerate reference_tracking.md")
    pt.add_argument("paper_dir")
    pt.set_defaults(func=cmd_track)

    ps = sub.add_parser("scan", help="shingle-match paper prose against cited references")
    ps.add_argument("paper_dir")
    ps.add_argument("--shingle-n", type=int, default=DEFAULT_SHINGLE_N,
                    help=f"shingle size in tokens (default: {DEFAULT_SHINGLE_N})")
    ps.add_argument("--min-run", type=int, default=DEFAULT_MIN_RUN,
                    help=f"minimum run length in tokens (default: {DEFAULT_MIN_RUN})")
    ps.add_argument("--no-filter", action="store_true",
                    help="disable generic-phrase filter (show raw matches)")
    ps.add_argument("--out", help="output path (default: paper_dir/literature/plagiarism_findings.md)")
    ps.set_defaults(func=cmd_scan)

    po = sub.add_parser("overlap", help="cross-paper overlap scan across 2+ papers")
    po.add_argument("paper_dirs", nargs="+")
    po.add_argument("--shingle-n", type=int, default=10,
                    help="shingle size in tokens (default: 10)")
    po.add_argument("--out", help="output path (default: ./overlap_report.md)")
    po.set_defaults(func=cmd_overlap)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
