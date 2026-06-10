"""Render a single, self-contained HTML integrity report.

Combines the sanity, scan, and (optional) verify results into one shareable
file with a PASS/WARN/FAIL verdict, color-coded scan confidence, and
side-by-side paper-vs-source context. Stdlib only — inline CSS, no assets.
"""
from __future__ import annotations

from html import escape

_STATUS_COLOR = {"PASS": "#1a7f37", "WARN": "#9a6700", "FAIL": "#cf222e"}

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; color: #1f2328; background: #f6f8fa; }
header { padding: 28px 32px; background: #fff; border-bottom: 1px solid #d0d7de; }
h1 { margin: 0; font-size: 20px; }
.sub { color: #57606a; margin-top: 4px; }
.verdict { display: inline-block; margin-top: 14px; padding: 6px 18px; border-radius: 999px;
           color: #fff; font-weight: 700; letter-spacing: .04em; }
main { max-width: 980px; margin: 0 auto; padding: 24px 32px 64px; }
h2 { font-size: 16px; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #d0d7de; }
.cards { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 20px; }
.card { flex: 1 1 200px; background: #fff; border: 1px solid #d0d7de; border-radius: 10px; padding: 16px; }
.card .n { font-size: 26px; font-weight: 700; }
.card .lbl { color: #57606a; font-size: 13px; text-transform: uppercase; letter-spacing: .03em; }
.banner { background: #ffebe9; border: 1px solid #ff818266; border-radius: 10px; padding: 16px 20px; margin: 20px 0; }
.banner.warn { background: #fff8c5; border-color: #d4a72c66; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d0d7de; border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid #eaeef2; font-size: 14px; vertical-align: top; }
th { background: #f6f8fa; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; color: #57606a; }
tr:last-child td { border-bottom: 0; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 6px; color: #fff; font-weight: 700; font-size: 12px; }
.finding { background: #fff; border: 1px solid #d0d7de; border-radius: 10px; padding: 14px 16px; margin: 12px 0; }
.finding .meta { color: #57606a; font-size: 13px; margin-bottom: 8px; }
.ctx { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.ctx > div { background: #f6f8fa; border-radius: 8px; padding: 10px 12px; }
.ctx .k { font-size: 11px; text-transform: uppercase; color: #57606a; letter-spacing: .03em; }
.sev-error { color: #cf222e; } .sev-warning { color: #9a6700; } .sev-info { color: #57606a; }
.empty { color: #1a7f37; font-weight: 600; }
footer { color: #8c959f; font-size: 12px; padding: 24px 32px; }
@media (max-width: 640px) { .ctx { grid-template-columns: 1fr; } }
"""


def _score_color(score: float) -> str:
    if score >= 0.6:
        return "#cf222e"
    if score >= 0.4:
        return "#9a6700"
    return "#1a7f37"


def render_html_report(paper_label: str, *, status: str = "PASS", scan_date: str = "",
                       sanity_issues: list | None = None,
                       scan_result: dict | None = None,
                       verify_results: list | None = None,
                       max_findings: int = 50) -> str:
    """Render the combined report as a self-contained HTML string."""
    sanity_issues = sanity_issues or []
    out: list[str] = []
    out.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    out.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    out.append(f"<title>refscan report — {escape(paper_label)}</title>")
    out.append(f"<style>{_CSS}</style></head><body>")

    color = _STATUS_COLOR.get(status, "#57606a")
    out.append("<header><h1>refscan integrity report</h1>")
    sub = escape(paper_label) + (f" · {escape(scan_date)}" if scan_date else "")
    out.append(f"<div class='sub'>{sub}</div>")
    out.append(f"<div class='verdict' style='background:{color}'>{escape(status)}</div></header>")
    out.append("<main>")

    n_err = sum(1 for i in sanity_issues if i.severity == "error")
    n_warn = sum(1 for i in sanity_issues if i.severity == "warning")
    findings = (scan_result or {}).get("findings", [])
    top_score = findings[0]["score"] if findings else 0.0
    n_retracted = sum(1 for r in (verify_results or []) if getattr(r, "retracted", False))

    # Summary cards
    out.append("<div class='cards'>")
    out.append(f"<div class='card'><div class='n'>{n_err}/{n_warn}</div>"
               "<div class='lbl'>sanity errors / warnings</div></div>")
    if scan_result is not None:
        out.append(f"<div class='card'><div class='n'>{len(findings)}</div>"
                   f"<div class='lbl'>scan findings · top {top_score:.2f}</div></div>")
    if verify_results is not None:
        n_nf = sum(1 for r in verify_results if r.verdict == "not-found")
        out.append(f"<div class='card'><div class='n'>{n_nf}</div>"
                   "<div class='lbl'>verify: not found</div></div>")
        out.append(f"<div class='card'><div class='n'>{n_retracted}</div>"
                   "<div class='lbl'>retracted</div></div>")
    out.append("</div>")

    # Retracted banner
    retracted = [r for r in (verify_results or []) if getattr(r, "retracted", False)]
    if retracted:
        out.append("<div class='banner'><strong>🚨 Retracted papers cited "
                   f"({len(retracted)}).</strong> Remove or replace these.<ul>")
        for r in retracted:
            doi = r.best_match.doi if r.best_match else ""
            link = (f" — <a href='https://doi.org/{escape(doi)}'>{escape(doi)}</a>"
                    if doi else "")
            out.append(f"<li><code>{escape(r.key)}</code>: {escape(r.bib_title)}{link}</li>")
        out.append("</ul></div>")

    # Scan findings
    out.append("<h2>Plagiarism scan</h2>")
    if scan_result is None:
        out.append("<p class='sev-warning'>Skipped — no reference PDFs or section files.</p>")
    elif not findings:
        out.append("<p class='empty'>✓ No matches above the noise threshold.</p>")
    else:
        shown = findings[:max_findings]
        for f in shown:
            c = _score_color(f["score"])
            out.append("<div class='finding'>")
            out.append(f"<div class='meta'><span class='badge' style='background:{c}'>"
                       f"{f['score']:.2f}</span> &nbsp; {f['run_len']} words · "
                       f"ref <code>{escape(f['bibkey'])}</code> · "
                       f"section <code>{escape(f['section'])}</code></div>")
            out.append("<div class='ctx'>")
            out.append(f"<div><div class='k'>your paper</div><span class='mono'>…"
                       f"{escape(f['paper_context'])}…</span></div>")
            out.append(f"<div><div class='k'>reference</div><span class='mono'>…"
                       f"{escape(f['ref_context'])}…</span></div>")
            out.append("</div></div>")
        if len(findings) > max_findings:
            out.append(f"<p class='sub'>…and {len(findings) - max_findings} more "
                       "(see the markdown report).</p>")

    # Sanity
    out.append("<h2>Bib hygiene</h2>")
    if not sanity_issues:
        out.append("<p class='empty'>✓ No issues.</p>")
    else:
        out.append("<table><tr><th>Severity</th><th>Key</th><th>Issue</th></tr>")
        rank = {"error": 0, "warning": 1, "info": 2}
        for i in sorted(sanity_issues, key=lambda x: (rank.get(x.severity, 9), x.category)):
            msg = i.message.split(": ", 1)[-1] if ": " in i.message else i.message
            out.append(f"<tr><td class='sev-{escape(i.severity)}'>{escape(i.severity)}</td>"
                       f"<td><code>{escape(i.key or '—')}</code></td>"
                       f"<td>{escape(msg)}</td></tr>")
        out.append("</table>")

    # Verify
    if verify_results is not None:
        out.append("<h2>Reference verification</h2>")
        not_found = [r for r in verify_results if r.verdict == "not-found"]
        if not not_found:
            out.append("<p class='empty'>✓ No likely-fabricated references.</p>")
        else:
            out.append("<div class='banner warn'><strong>Not found "
                       f"({len(not_found)})</strong> — verify on Google Scholar before "
                       "trusting; remove if fabricated.<ul>")
            for r in not_found:
                out.append(f"<li><code>{escape(r.key)}</code>: {escape(r.bib_title)}</li>")
            out.append("</ul></div>")

    out.append("</main>")
    out.append("<footer>Generated by refscan · this is a self-contained file — "
               "open in any browser or share it.</footer>")
    out.append("</body></html>")
    return "".join(out)
