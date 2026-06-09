"""Command-line entry point for refscan."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from . import __version__
from .bib import parse_bib, ref_pdf_path
from .fetch import fetch_paper, was_rate_limited
from .layout import resolve_layout
from .overlap import detect_overlap, render_overlap_md
from .release import execute as release_execute, plan_release
from .sanity import render_sanity_md, run_sanity, summarize
from .scan import (
    DEFAULT_MIN_RUN,
    DEFAULT_SHINGLE_N,
    render_findings_md,
    render_findings_terminal,
    scan,
)
from .track import generate_tracking_md, write_config_template
from .verify import render_verification_md, verify_paper


def _today() -> str:
    return dt.date.today().isoformat()


def _paper_label(paper_dir: Path) -> str:
    return paper_dir.name


def cmd_init(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir)
    layout.refs_dir.mkdir(parents=True, exist_ok=True)
    layout.cache_dir.mkdir(parents=True, exist_ok=True)
    if not layout.bib.exists():
        print(f"warning: no bib file found at {layout.bib}", file=sys.stderr)
    cfg = write_config_template(paper_dir)
    if cfg:
        print(f"wrote config template {cfg}")
    # Write an initial tracking file
    generate_tracking_md(paper_dir, _paper_label(paper_dir),
                         bib_path=layout.bib, refs_dir=layout.refs_dir,
                         output_path=layout.tracking_md, scan_date=_today())
    print(f"initialized {layout.literature_dir}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib)
    refs_dir = layout.refs_dir
    refs_dir.mkdir(parents=True, exist_ok=True)

    entries = parse_bib(layout.bib)
    n_before = sum(1 for e in entries
                   if (p := ref_pdf_path(refs_dir, e.key)) and p.exists())
    results = fetch_paper(
        entries, refs_dir,
        try_s2=not args.no_s2,
        max_workers=args.workers,
        progress=True,
    )
    downloaded = sum(1 for r in results if r["status"] == "downloaded")
    failed = sum(1 for r in results if r["status"] == "download-failed")
    not_found = sum(1 for r in results if r["status"] == "not-found")
    unsafe = sum(1 for r in results if r["status"] == "unsafe-key")
    msg = (f"\nbefore: {n_before} / {len(entries)}  |  "
           f"newly downloaded: {downloaded}  |  "
           f"download-failed: {failed}  |  "
           f"not found: {not_found}")
    if unsafe:
        msg += f"  |  unsafe-key: {unsafe}"
    print(msg)
    # Refresh tracking file to reflect new state
    generate_tracking_md(paper_dir, _paper_label(paper_dir),
                         bib_path=layout.bib, refs_dir=layout.refs_dir,
                         output_path=layout.tracking_md, scan_date=_today())
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib)
    path, counts = generate_tracking_md(
        paper_dir, _paper_label(paper_dir),
        bib_path=layout.bib, refs_dir=layout.refs_dir,
        output_path=layout.tracking_md, scan_date=_today(),
    )
    print(f"wrote {path}")
    for bucket, n in counts.items():
        print(f"  {bucket}: {n}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib, sections=args.sections)
    if not layout.section_files:
        print(f"error: no section .tex files found (sections="
              f"{args.sections or 'paper/sections'})", file=sys.stderr)
        return 1
    if not layout.refs_dir.is_dir():
        print(f"error: refs dir not found at {layout.refs_dir} (run "
              f"`refscan init` / `fetch` first)", file=sys.stderr)
        return 1
    result = scan(
        section_files=list(layout.section_files),
        refs_dir=layout.refs_dir,
        cache_dir=layout.cache_dir,
        shingle_n=args.shingle_n,
        min_run=args.min_run,
        filter_generic=not args.no_filter,
    )
    report = render_findings_md(_paper_label(paper_dir), result, scan_date=_today())
    out_path = Path(args.out) if args.out else layout.findings_md
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"refs indexed: {len(result['refs_indexed'])}  |  "
          f"failed: {len(result['refs_failed'])}  |  "
          f"findings: {len(result['findings'])}")
    print(f"wrote {out_path}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib)
    if not layout.bib.exists():
        print(f"error: no references.bib at {layout.bib}", file=sys.stderr)
        return 1
    use_s2 = not args.no_s2
    results = verify_paper(
        paper_dir=paper_dir,
        use_s2=use_s2,
        refresh=args.refresh,
        bib=args.bib,
    )
    report = render_verification_md(
        _paper_label(paper_dir), results, scan_date=_today(),
        s2_rate_limited=was_rate_limited(),
        s2_used=use_s2,
    )
    out_path = Path(args.out) if args.out else layout.verification_md
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    counts = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    print(f"\nwrote {out_path}")
    for v in ("not-found", "weak-match", "metadata-drift", "verified", "skipped", "api-error"):
        if v in counts:
            print(f"  {v}: {counts[v]}")
    return 0


def cmd_sanity(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib, sections=args.sections)
    issues, n_entries, n_cited = run_sanity(paper_dir, bib=args.bib, sections=args.sections)
    report = render_sanity_md(_paper_label(paper_dir), issues,
                                total_entries=n_entries, total_cited=n_cited,
                                scan_date=_today())
    out_path = Path(args.out) if args.out else layout.sanity_md
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    counts = summarize(issues)
    print(f"wrote {out_path}")
    print(f"  entries: {n_entries}  |  cited: {n_cited}")
    print(f"  errors: {counts['error']}  |  warnings: {counts['warning']}  |  info: {counts['info']}")
    return 1 if counts["error"] > 0 else 0


def cmd_watch(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, sections=args.sections)
    if not layout.section_files:
        print(f"error: no section .tex files found (sections="
              f"{args.sections or 'paper/sections'})", file=sys.stderr)
        return 1
    if not layout.refs_dir.is_dir():
        print(f"error: no refs dir at {layout.refs_dir}", file=sys.stderr)
        return 1

    # Re-resolve each poll so new/removed section files are picked up.
    def _watched() -> list[Path]:
        return resolve_layout(paper_dir, sections=args.sections).cite_files

    print(f"refscan watch: {paper_dir.name}", flush=True)
    print(f"  watching: {len(layout.section_files)} section file(s)", flush=True)
    print(f"  poll interval: {args.interval}s", flush=True)
    print(f"  showing: top {args.top} matches per scan", flush=True)
    print("  press Ctrl-C to stop\n", flush=True)

    def _scan_and_print(label: str) -> None:
        ts = dt.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {label}", flush=True)
        lay = resolve_layout(paper_dir, sections=args.sections)
        result = scan(
            section_files=list(lay.section_files), refs_dir=lay.refs_dir,
            cache_dir=lay.cache_dir,
            shingle_n=args.shingle_n, min_run=args.min_run,
        )
        print(render_findings_terminal(result, top_n=args.top), flush=True)
        print(flush=True)

    last_mtimes = {f: f.stat().st_mtime for f in _watched()}
    _scan_and_print("initial scan")

    try:
        while True:
            time.sleep(args.interval)
            current = {f: f.stat().st_mtime for f in _watched()}
            changed = []
            for f, mt in current.items():
                if f not in last_mtimes or mt > last_mtimes[f]:
                    changed.append(f)
            removed = [f for f in last_mtimes if f not in current]
            if changed or removed:
                last_mtimes = current
                desc_parts = []
                if changed:
                    desc_parts.append("changed: " + ", ".join(c.name for c in changed))
                if removed:
                    desc_parts.append("removed: " + ", ".join(r.name for r in removed))
                _scan_and_print(" | ".join(desc_parts))
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0


def cmd_release(args: argparse.Namespace) -> int:
    try:
        plan = plan_release(
            kind=args.kind,
            push=args.push,
            run_tests=not args.no_test,
            dry_run=args.dry_run,
        )
    except (RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return release_execute(plan)


def cmd_overlap(args: argparse.Namespace) -> int:
    paper_dirs = [Path(p).resolve() for p in args.paper_dirs]
    paper_sections: dict[str, list[Path]] = {}
    for p in paper_dirs:
        files = list(resolve_layout(p).section_files)
        if not files:
            print(f"warning: {p.name} has no section .tex files", file=sys.stderr)
        paper_sections[p.name] = files
    result = detect_overlap(paper_sections, shingle_n=args.shingle_n)
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
    pf.add_argument("--bib", help="path to references.bib relative to paper_dir "
                                  "(overrides refscan.json; default paper/references.bib)")
    pf.add_argument("--no-s2", action="store_true",
                    help="skip Semantic Scholar fallback (arXiv only)")
    pf.add_argument("--workers", type=int, default=5,
                    help="parallel download workers (default: 5; set 1 for "
                         "fully sequential). API resolution is always sequential "
                         "to respect rate limits.")
    pf.set_defaults(func=cmd_fetch)

    pt = sub.add_parser("track", help="regenerate reference_tracking.md")
    pt.add_argument("paper_dir")
    pt.add_argument("--bib", help="path to references.bib relative to paper_dir "
                                  "(overrides refscan.json)")
    pt.set_defaults(func=cmd_track)

    _SECTIONS_HELP = ("sections source relative to paper_dir: a directory, a single "
                      ".tex file, or a glob (overrides refscan.json; default paper/sections)")
    _BIB_HELP = ("path to references.bib relative to paper_dir "
                 "(overrides refscan.json; default paper/references.bib)")

    ps = sub.add_parser("scan", help="shingle-match paper prose against cited references")
    ps.add_argument("paper_dir")
    ps.add_argument("--bib", help=_BIB_HELP)
    ps.add_argument("--sections", help=_SECTIONS_HELP)
    ps.add_argument("--shingle-n", type=int, default=DEFAULT_SHINGLE_N,
                    help=f"shingle size in tokens (default: {DEFAULT_SHINGLE_N})")
    ps.add_argument("--min-run", type=int, default=DEFAULT_MIN_RUN,
                    help=f"minimum run length in tokens (default: {DEFAULT_MIN_RUN})")
    ps.add_argument("--no-filter", action="store_true",
                    help="disable generic-phrase filter (show raw matches)")
    ps.add_argument("--out", help="output path (default: paper_dir/literature/plagiarism_findings.md)")
    ps.set_defaults(func=cmd_scan)

    pv = sub.add_parser("verify", help="check bib entries against arXiv + Semantic Scholar")
    pv.add_argument("paper_dir")
    pv.add_argument("--bib", help=_BIB_HELP)
    pv.add_argument("--no-s2", action="store_true",
                    help="skip Semantic Scholar (arXiv only, faster)")
    pv.add_argument("--refresh", action="store_true",
                    help="ignore cached results and re-query APIs")
    pv.add_argument("--out", help="output path (default: paper_dir/literature/verification_report.md)")
    pv.set_defaults(func=cmd_verify)

    pn = sub.add_parser("sanity-stats", help="bib hygiene report (cited vs defined, dupes, missing fields)")
    pn.add_argument("paper_dir")
    pn.add_argument("--bib", help=_BIB_HELP)
    pn.add_argument("--sections", help=_SECTIONS_HELP)
    pn.add_argument("--out", help="output path (default: paper_dir/literature/sanity_report.md)")
    pn.set_defaults(func=cmd_sanity)

    pw = sub.add_parser("watch", help="re-run scan whenever a section .tex file is saved")
    pw.add_argument("paper_dir")
    pw.add_argument("--sections", help=_SECTIONS_HELP)
    pw.add_argument("--interval", type=float, default=1.0,
                    help="poll interval in seconds (default: 1.0)")
    pw.add_argument("--top", type=int, default=5,
                    help="number of top matches to show per scan (default: 5)")
    pw.add_argument("--shingle-n", type=int, default=DEFAULT_SHINGLE_N,
                    help=f"shingle size in tokens (default: {DEFAULT_SHINGLE_N})")
    pw.add_argument("--min-run", type=int, default=DEFAULT_MIN_RUN,
                    help=f"minimum run length in tokens (default: {DEFAULT_MIN_RUN})")
    pw.set_defaults(func=cmd_watch)

    pr = sub.add_parser(
        "release",
        help="(maintainer-only) bump version, run tests, commit, tag, optionally push",
    )
    pr.add_argument("kind",
                    help="patch | minor | major | explicit X.Y.Z version")
    pr.add_argument("--push", action="store_true",
                    help="git push branch + tag after committing (default: skip)")
    pr.add_argument("--no-test", action="store_true",
                    help="skip pytest run (default: run tests)")
    pr.add_argument("--dry-run", action="store_true",
                    help="show what would happen without modifying anything")
    pr.set_defaults(func=cmd_release)

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
