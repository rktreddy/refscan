"""Command-line entry point for refscan."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from . import __version__
from .bib import parse_bib, ref_pdf_path
from .color import bold, green, red, yellow
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


def _note_autodetect(layout) -> None:
    """Tell the user when bib/sections were auto-discovered (not configured)."""
    if layout.auto_bib:
        print(f"note: auto-detected bib at {layout.bib} "
              f"(set `bib` in refscan.json to pin it)", file=sys.stderr)
    if layout.auto_sections:
        print(f"note: auto-detected {len(layout.section_files)} section .tex "
              f"file(s) (set `sections` in refscan.json to pin them)", file=sys.stderr)


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
    _note_autodetect(layout)
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
    _note_autodetect(layout)
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
    _note_autodetect(layout)
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
    _note_autodetect(layout)
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
    n_retracted = sum(1 for r in results if r.retracted)
    if n_retracted:
        print(red(f"  🚨 retracted: {n_retracted}  (see report)"))
    for v in ("not-found", "weak-match", "metadata-drift", "verified", "skipped", "api-error"):
        if v in counts:
            print(f"  {v}: {counts[v]}")
    return 0


def cmd_sanity(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib, sections=args.sections)
    _note_autodetect(layout)
    issues, n_entries, n_cited = run_sanity(paper_dir, bib=args.bib, sections=args.sections)
    report = render_sanity_md(_paper_label(paper_dir), issues,
                                total_entries=n_entries, total_cited=n_cited,
                                scan_date=_today())
    out_path = Path(args.out) if args.out else layout.sanity_md
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    counts = summarize(issues)
    print(f"wrote {out_path}")
    err_s = red(str(counts["error"])) if counts["error"] else "0"
    warn_s = yellow(str(counts["warning"])) if counts["warning"] else "0"
    print(f"  entries: {n_entries}  |  cited: {n_cited}")
    print(f"  errors: {err_s}  |  warnings: {warn_s}  |  info: {counts['info']}")
    return 1 if counts["error"] > 0 else 0


def cmd_watch(args: argparse.Namespace) -> int:
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, sections=args.sections)
    _note_autodetect(layout)
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


def cmd_fix(args: argparse.Namespace) -> int:
    """Apply safe bib metadata corrections (DOIs, drifted years) found by verify."""
    from .bib import parse_bib as _parse_bib
    from .fix import apply_fixes, compute_fixes

    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib)
    _note_autodetect(layout)
    if not layout.bib.exists():
        print(f"error: no references.bib at {layout.bib}", file=sys.stderr)
        return 1

    results = verify_paper(paper_dir=paper_dir, use_s2=not args.no_s2,
                           refresh=args.refresh, bib=args.bib, progress=True)
    entries = _parse_bib(layout.bib)
    fixes = compute_fixes(entries, {r.key: r for r in results})

    if not fixes:
        print("\nno safe metadata fixes found (DOIs present, years agree).")
        return 0

    print(f"\nproposed fixes ({len(fixes)}):")
    for f in fixes:
        print(f"  {f.key}: {f.field}  {f.old or '(none)'} → {f.new}"
              f"   [{f.source}: {f.reason}]")

    if not args.apply:
        print("\n(preview only — re-run with --apply to write these; "
              "a .bak backup is made first)")
        return 0

    backup = layout.bib.with_suffix(layout.bib.suffix + ".bak")
    backup.write_text(layout.bib.read_text())
    n = apply_fixes(layout.bib, fixes)
    print(f"\napplied {n} fix(es) to {layout.bib}\n  backup: {backup}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """One-shot integrity check: layout + sanity + scan (+ optional verify)."""
    paper_dir = Path(args.paper_dir).resolve()
    layout = resolve_layout(paper_dir, bib=args.bib, sections=args.sections)
    label = _paper_label(paper_dir)
    n_sec = len(layout.section_files)
    n_refs = len(list(layout.refs_dir.glob("*.pdf"))) if layout.refs_dir.is_dir() else 0

    print(f"refscan check: {label}")
    print(f"  bib:      {layout.bib}{'  (auto-detected)' if layout.auto_bib else ''}")
    print(f"  sections: {n_sec} .tex file(s)"
          f"{'  (auto-detected)' if layout.auto_sections else ''}")
    print(f"  refs:     {n_refs} PDF(s) in {layout.refs_dir}\n")

    if not layout.bib.exists():
        print(f"error: no references.bib found (looked at {layout.bib}). "
              f"Set `bib` in refscan.json or pass --bib.", file=sys.stderr)
        return 1

    status = "PASS"
    lines: list[str] = []

    def _degrade(to: str) -> None:
        nonlocal status
        rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
        if rank[to] > rank[status]:
            status = to

    # Sanity (offline)
    issues, n_entries, n_cited = run_sanity(paper_dir, bib=args.bib, sections=args.sections)
    sc = summarize(issues)
    layout.sanity_md.parent.mkdir(parents=True, exist_ok=True)
    layout.sanity_md.write_text(render_sanity_md(
        label, issues, total_entries=n_entries, total_cited=n_cited, scan_date=_today()))
    lines.append(f"  sanity:  {sc['error']} error(s), {sc['warning']} warning(s)  "
                 f"({n_entries} entries, {n_cited} cited)")
    if sc["error"]:
        _degrade("FAIL")
    elif sc["warning"]:
        _degrade("WARN")

    # Scan (offline)
    scan_result = None
    if n_sec == 0:
        lines.append("  scan:    skipped (no section .tex files found)")
        _degrade("WARN")
    elif n_refs == 0:
        lines.append("  scan:    skipped (no reference PDFs — run `refscan fetch`)")
        _degrade("WARN")
    else:
        scan_result = scan(section_files=list(layout.section_files), refs_dir=layout.refs_dir,
                           cache_dir=layout.cache_dir, shingle_n=args.shingle_n, min_run=args.min_run)
        findings = scan_result["findings"]
        top = findings[0]["score"] if findings else 0.0
        layout.findings_md.write_text(render_findings_md(label, scan_result, scan_date=_today()))
        lines.append(f"  scan:    {len(findings)} finding(s), top confidence {top:.2f}  "
                     f"({len(scan_result['refs_indexed'])} refs indexed)")
        if findings and top >= 0.5:
            _degrade("WARN")

    # Verify (network, opt-in)
    verify_results = None
    if args.verify:
        use_s2 = not args.no_s2
        results = verify_paper(paper_dir=paper_dir, use_s2=use_s2,
                               refresh=args.refresh, bib=args.bib, progress=False)
        verify_results = results
        vc: dict[str, int] = {}
        for r in results:
            vc[r.verdict] = vc.get(r.verdict, 0) + 1
        layout.verification_md.write_text(render_verification_md(
            label, results, scan_date=_today(),
            s2_rate_limited=was_rate_limited(), s2_used=use_s2))
        n_retracted = sum(1 for r in results if r.retracted)
        retr = f", 🚨 {n_retracted} retracted" if n_retracted else ""
        lines.append(
            f"  verify:  {vc.get('verified', 0)} verified, {vc.get('not-found', 0)} not-found, "
            f"{vc.get('weak-match', 0)} weak, {vc.get('metadata-drift', 0)} drift, "
            f"{vc.get('api-error', 0)} api-error{retr}")
        if vc.get("not-found", 0) or n_retracted:
            _degrade("FAIL")
        elif vc.get("weak-match", 0) or vc.get("metadata-drift", 0):
            _degrade("WARN")
    else:
        lines.append("  verify:  skipped (pass --verify to check refs against arXiv/S2; uses network)")

    if args.html:
        from .report import render_html_report
        html_path = layout.literature_dir / "report.html"
        html_path.write_text(render_html_report(
            label, status=status, scan_date=_today(),
            sanity_issues=issues, scan_result=scan_result, verify_results=verify_results))
        lines.append(f"  html:    {html_path}")

    if args.json:
        from .report import render_json_report
        json_path = layout.literature_dir / "report.json"
        json_path.write_text(render_json_report(
            label, version=__version__, status=status, scan_date=_today(),
            sanity_issues=issues, scan_result=scan_result, verify_results=verify_results))
        lines.append(f"  json:    {json_path}")

    if args.sarif:
        from .report import render_sarif_report

        def _rel(p: Path) -> str:
            try:
                return str(p.relative_to(layout.paper_dir))
            except ValueError:
                return p.name

        sarif_path = layout.literature_dir / "report.sarif"
        sarif_path.write_text(render_sarif_report(
            version=__version__, bib_uri=_rel(layout.bib),
            section_uris={p.name: _rel(p) for p in layout.section_files},
            sanity_issues=issues, scan_result=scan_result, verify_results=verify_results))
        lines.append(f"  sarif:   {sarif_path}")

    print("results:")
    for ln in lines:
        print(ln)
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[status]
    color_fn = {"PASS": green, "WARN": yellow, "FAIL": red}[status]
    print(f"\n{icon} {color_fn(bold(status))}    reports in {layout.literature_dir}/")
    return 1 if status == "FAIL" else 0


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

    pfx = sub.add_parser(
        "fix",
        help="apply safe bib metadata corrections (add DOIs, fix drifted years) found by verify",
    )
    pfx.add_argument("paper_dir")
    pfx.add_argument("--bib", help=_BIB_HELP)
    pfx.add_argument("--apply", action="store_true",
                     help="write fixes to the bib (default: preview only); a .bak backup is made first")
    pfx.add_argument("--no-s2", action="store_true",
                     help="skip Semantic Scholar (arXiv + OpenAlex + Crossref only)")
    pfx.add_argument("--refresh", action="store_true",
                     help="ignore cached verify results and re-query APIs")
    pfx.set_defaults(func=cmd_fix)

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

    pck = sub.add_parser(
        "check",
        help="one-shot integrity check: layout + sanity + scan (+ optional verify) "
             "with a PASS/WARN/FAIL verdict",
    )
    pck.add_argument("paper_dir")
    pck.add_argument("--bib", help=_BIB_HELP)
    pck.add_argument("--sections", help=_SECTIONS_HELP)
    pck.add_argument("--verify", action="store_true",
                     help="also verify bib entries against arXiv/Semantic Scholar (network)")
    pck.add_argument("--html", action="store_true",
                     help="also write a self-contained literature/report.html")
    pck.add_argument("--json", action="store_true",
                     help="also write machine-readable literature/report.json")
    pck.add_argument("--sarif", action="store_true",
                     help="also write literature/report.sarif (GitHub code-scanning)")
    pck.add_argument("--no-s2", action="store_true",
                     help="with --verify: skip Semantic Scholar (arXiv only)")
    pck.add_argument("--refresh", action="store_true",
                     help="with --verify: ignore cached results")
    pck.add_argument("--shingle-n", type=int, default=DEFAULT_SHINGLE_N,
                     help=f"shingle size in tokens (default: {DEFAULT_SHINGLE_N})")
    pck.add_argument("--min-run", type=int, default=DEFAULT_MIN_RUN,
                     help=f"minimum run length in tokens (default: {DEFAULT_MIN_RUN})")
    pck.set_defaults(func=cmd_check)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
