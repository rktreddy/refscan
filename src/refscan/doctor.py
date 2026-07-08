"""Environment self-check (``refscan doctor``).

Fast and side-effect-free by design: backend checks import modules but never
load or download embedding models; network probes use a short timeout and are
skippable with ``--no-network``.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .color import bold, dim, green, red, yellow
from .fetch import (
    ARXIV_API,
    CROSSREF_API,
    DEFAULT_USER_AGENT,
    OPENALEX_API,
    S2_API,
    _http_get,
)
from .layout import resolve_layout
from .semantic import _IMPORT_NAME, _INSTALL_HINT, available_backends

_SOURCES = (("arXiv", ARXIV_API), ("Semantic Scholar", S2_API),
            ("OpenAlex", OPENALEX_API), ("Crossref", CROSSREF_API))


@dataclass
class CheckResult:
    """One diagnostic finding."""

    name: str
    status: str  # "ok" | "warn" | "fail" | "info"
    message: str
    hint: str = ""


def check_refscan() -> CheckResult:
    """Report refscan's version and install location."""
    pkg_dir = Path(__file__).resolve().parent
    return CheckResult("refscan", "info", f"v{__version__} at {pkg_dir}")


def check_python() -> CheckResult:
    """refscan targets Python 3.10+."""
    ver = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        return CheckResult("python", "ok", f"Python {ver}")
    return CheckResult("python", "fail", f"Python {ver} is too old",
                       hint="refscan needs Python 3.10 or newer")


def check_pdftotext() -> CheckResult:
    """pdftotext (poppler) is the one runtime system dependency (scan/check)."""
    path = shutil.which("pdftotext")
    if path is None:
        return CheckResult(
            "pdftotext", "fail", "not found on PATH — scan/check cannot extract PDF text",
            hint="install poppler: `brew install poppler` (macOS) or "
                 "`apt install poppler-utils` (Debian/Ubuntu)")
    version = ""
    try:
        proc = subprocess.run([path, "-v"], capture_output=True, text=True, timeout=10)
        first = (proc.stderr or proc.stdout).strip().splitlines()
        version = first[0] if first else ""
    except (OSError, subprocess.SubprocessError):
        pass
    return CheckResult("pdftotext", "ok", version or path)


def check_semantic_backends() -> CheckResult:
    """Which optional semscan backend is installed and importable, if any."""
    installed = available_backends()
    if not installed:
        return CheckResult("semantic backends", "warn",
                           "none installed — semscan unavailable (all other "
                           "commands work)",
                           hint=_INSTALL_HINT)
    broken: list[str] = []
    for b in installed:
        try:
            importlib.import_module(_IMPORT_NAME[b])
        except Exception as ex:  # import-time breakage, e.g. torch/NumPy conflict
            broken.append(f"{b} ({type(ex).__name__}: {ex})")
            continue
        note = f" ({len(broken)} broken: {'; '.join(broken)})" if broken else ""
        return CheckResult("semantic backends", "ok",
                           f"semscan will use {b}{note}")
    return CheckResult("semantic backends", "warn",
                       "installed but failing to import: " + "; ".join(broken),
                       hint="usually a torch/numpy version conflict — "
                            "`pip install model2vec` for the light backend")


def check_network(user_agent: str = DEFAULT_USER_AGENT,
                  timeout: int = 5) -> list[CheckResult]:
    """Probe each metadata source; any HTTP status (even an error) = reachable."""
    results = []
    for name, url in _SOURCES:
        _, status = _http_get(url, user_agent, timeout=timeout)
        if status is not None:
            results.append(CheckResult(f"{name} reachable", "ok", url))
        else:
            results.append(CheckResult(
                f"{name} reachable", "warn", f"no response from {url}",
                hint="network down or blocked — verify/fetch/cite need this source"))
    return results


def check_env() -> list[CheckResult]:
    """Optional env vars that improve API coverage."""
    results = []
    if os.environ.get("REFSCAN_CONTACT_EMAIL", "").strip():
        results.append(CheckResult("REFSCAN_CONTACT_EMAIL", "ok", "set"))
    else:
        results.append(CheckResult(
            "REFSCAN_CONTACT_EMAIL", "warn", "not set",
            hint="set it to join the OpenAlex/Crossref polite pools and enable "
                 "Unpaywall PDF resolution"))
    if os.environ.get("REFSCAN_S2_API_KEY", "").strip():
        results.append(CheckResult("REFSCAN_S2_API_KEY", "ok", "set"))
    else:
        results.append(CheckResult(
            "REFSCAN_S2_API_KEY", "warn", "not set",
            hint="unauthenticated Semantic Scholar throttles aggressively — "
                 "free key at https://www.semanticscholar.org/product/api"))
    return results


def check_layout(paper_dir: Path) -> list[CheckResult]:
    """Diagnose layout resolution for one paper directory."""
    layout = resolve_layout(paper_dir)
    results = []
    if layout.bib.exists():
        results.append(CheckResult("bib", "ok", str(layout.bib)))
    else:
        results.append(CheckResult(
            "bib", "fail", f"no references.bib found (looked at {layout.bib})",
            hint="set the path in refscan.json (`\"bib\": ...`) or pass --bib"))
    n_sections = len(layout.section_files)
    if n_sections:
        results.append(CheckResult("sections", "ok", f"{n_sections} .tex file(s)"))
    else:
        results.append(CheckResult(
            "sections", "warn", "no section .tex files found",
            hint="set `\"sections\"` in refscan.json or pass --sections"))
    n_pdfs = len(list(layout.refs_dir.glob("*.pdf"))) if layout.refs_dir.is_dir() else 0
    results.append(CheckResult("reference PDFs", "info",
                               f"{n_pdfs} PDF(s) in {layout.refs_dir}"))
    return results


def run_doctor(paper_dir: Path | None = None,
               network: bool = True) -> tuple[list[CheckResult], int]:
    """Run all checks; exit code is 1 iff any check failed."""
    results = [check_refscan(), check_python(), check_pdftotext(),
               check_semantic_backends()]
    results.extend(check_env())
    if network:
        results.extend(check_network())
    if paper_dir is not None:
        results.extend(check_layout(paper_dir))
    code = 1 if any(r.status == "fail" for r in results) else 0
    return results, code


_MARK = {"ok": ("✓", green), "warn": ("⚠", yellow),
         "fail": ("✗", red), "info": ("·", dim)}


def render(results: list[CheckResult]) -> str:
    """Colorized checklist plus a summary line."""
    width = max(len(r.name) for r in results) if results else 0
    lines = []
    for r in results:
        mark, style = _MARK[r.status]
        lines.append(f"  {style(mark)} {r.name.ljust(width)}  {r.message}")
        if r.hint:
            lines.append(f"    {' ' * width}{dim('↳ ' + r.hint)}")
    counts = {s: sum(1 for r in results if r.status == s)
              for s in ("ok", "warn", "fail")}
    summary = (f"{counts['ok']} ok, {counts['warn']} warning(s), "
               f"{counts['fail']} failure(s)")
    lines.append("")
    lines.append(bold(summary))
    return "\n".join(lines)
