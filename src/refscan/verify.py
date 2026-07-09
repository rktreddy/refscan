"""Verify bib entries exist by querying arXiv and Semantic Scholar.

For each bib entry:
  1. Query arXiv (and optionally Semantic Scholar) by title + author.
  2. Score each result against the bib entry's claimed metadata.
  3. Assign a verdict: verified / metadata-drift / weak-match / not-found.

Output: ``literature/verification_report.md`` with verdicts and best-match
metadata so the user can spot-fix or remove fabricated entries.

Always queries the API even if a PDF is already downloaded — substitute PDFs
need to be caught.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .bib import BibEntry, parse_bib, ref_pdf_path
from .fetch import (
    ARXIV_DELAY_S,
    CROSSREF_DELAY_S,
    DEFAULT_USER_AGENT,
    OPENALEX_DELAY_S,
    S2_API_KEY_ENV,
    S2_DELAY_S,
    arxiv_lookup_by_id,
    arxiv_search_metadata,
    crossref_lookup_by_doi,
    crossref_search_metadata,
    openalex_search_metadata,
    reset_rate_limit_state,
    semantic_scholar_search_metadata,
    was_rate_limited,
)
from .textproc import title_word_match
from .track import categorize, load_config


VERIFIED_TITLE_OVERLAP = 0.7
WEAK_TITLE_OVERLAP = 0.4
YEAR_DRIFT_TOLERANCE = 1  # years
ARXIV_DOI_PREFIX = "10.48550/"  # arXiv's own DOIs — not a published venue


@dataclass
class APIResult:
    """One candidate match returned from arXiv or Semantic Scholar."""
    source: str            # "arxiv" or "s2"
    title: str
    authors: list[str]
    year: str
    arxiv_id: str = ""
    doi: str = ""
    title_overlap: float = 0.0
    author_match: bool = False
    year_diff: int | None = None
    retracted: bool = False   # OpenAlex is_retracted on this candidate
    venue: str = ""           # published venue (journal/proceedings), "" if unknown
    container_type: str = ""  # "journal" | "proceedings" | ""


@dataclass
class VerifyResult:
    """Verification result for one bib entry."""
    key: str
    bib_title: str
    bib_first_author: str
    bib_year: str
    bib_pdf_present: bool
    verdict: str           # verified / metadata-drift / weak-match / not-found / skipped / api-error
    skip_reason: str = ""
    best_match: APIResult | None = None
    other_matches: list[APIResult] = field(default_factory=list)
    retracted: bool = False   # a confident match is flagged retracted by OpenAlex
    published_match: APIResult | None = None  # published version of a cited preprint


def _word_set(text: str) -> set[str]:
    """Lowercase word set, ignoring tokens shorter than 4 chars."""
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _title_overlap(bib_title: str, candidate_title: str) -> float:
    """Fraction of bib-title words present in candidate title.

    Uses the robust ``title_word_match`` from textproc so candidate titles that
    were extracted from letter-spaced PDF rendering (rare for API responses,
    but possible) are matched correctly.
    """
    return title_word_match(bib_title, candidate_title)


def _author_in(authors: list[str], surname: str) -> bool:
    if not surname or len(surname) < 3:
        return True  # nothing to check; don't penalize
    target = surname.lower()
    for a in authors:
        if target in a.lower():
            return True
    return False


def _score_candidate(entry: BibEntry, candidate: dict, source: str) -> APIResult:
    overlap = _title_overlap(entry.title, candidate.get("title", ""))
    authors = candidate.get("authors", [])
    a_match = _author_in(authors, entry.first_author)
    cy = candidate.get("year", "")
    year_diff: int | None = None
    if entry.year.isdigit() and cy.isdigit():
        year_diff = abs(int(entry.year) - int(cy))
    return APIResult(
        source=source,
        title=candidate.get("title", ""),
        authors=authors,
        year=cy,
        arxiv_id=candidate.get("arxiv_id", ""),
        doi=candidate.get("doi", ""),
        title_overlap=overlap,
        author_match=a_match,
        retracted=bool(candidate.get("retracted", False)),
        year_diff=year_diff,
        venue=candidate.get("venue", ""),
        container_type=candidate.get("container_type", ""),
    )


def is_preprint_citation(entry: BibEntry) -> bool:
    """True when ``entry`` cites an arXiv preprint with no published venue.

    arXiv signal: an explicit arXiv ID in any field, or an ``eprint`` field
    with ``archivePrefix = {arXiv}``. Published signals that disqualify: a
    non-arXiv DOI (arXiv's own ``10.48550/…`` doesn't count), a ``journal``
    that isn't the "arXiv preprint …" placeholder, or a ``booktitle``.
    """
    f = entry.fields
    has_arxiv = bool(entry.explicit_arxiv_id) or (
        "eprint" in f and f.get("archiveprefix", "").strip().lower() == "arxiv")
    if not has_arxiv:
        return False
    doi = entry.doi
    if doi and not doi.lower().startswith(ARXIV_DOI_PREFIX):
        return False
    journal = f.get("journal", "")
    if journal and "arxiv" not in journal.lower():
        return False
    if f.get("booktitle", "").strip():
        return False
    return True


def find_published_match(candidates: list[APIResult]) -> APIResult | None:
    """First candidate that confidently identifies a *published* version.

    Restricted to Crossref/OpenAlex (publication-record sources), confident
    title overlap + author match, a non-arXiv DOI, and a known venue (needed
    to write a ``journal`` field; also excludes repository-only records).
    """
    for c in candidates:
        if (c.source in ("crossref", "openalex")
                and c.title_overlap >= VERIFIED_TITLE_OVERLAP
                and c.author_match
                and c.doi and not c.doi.lower().startswith(ARXIV_DOI_PREFIX)
                and c.venue):
            return c
    return None


def lookup_published_version(entry: BibEntry,
                             user_agent: str = DEFAULT_USER_AGENT) -> APIResult | None:
    """Targeted published-version lookup for a preprint citation.

    Title-search candidates often miss the published record (or drown it in
    same-title review/annotation records), so ask arXiv itself: once a
    preprint is published, its arXiv record usually carries the author-linked
    published DOI and a ``journal_ref``. The DOI is then resolved via
    Crossref/OpenAlex for a clean venue name, falling back to the raw
    ``journal_ref``. The arXiv record must confidently match the entry's
    title and author — which also guards against a typo'd arXiv ID.
    """
    aid = entry.explicit_arxiv_id or entry.fields.get("eprint", "").strip()
    if not aid:
        return None
    rec = arxiv_lookup_by_id(aid, user_agent=user_agent)
    if not rec:
        return None
    arx = _score_candidate(entry, rec, "arxiv")
    if arx.title_overlap < VERIFIED_TITLE_OVERLAP or not arx.author_match:
        return None
    pdoi = rec.get("doi", "")
    if not pdoi or pdoi.lower().startswith(ARXIV_DOI_PREFIX):
        return None  # no published DOI linked — still preprint-only
    meta = crossref_lookup_by_doi(pdoi, user_agent=user_agent)
    if meta and meta.get("venue"):
        c = _score_candidate(entry, meta, "crossref")
        if (c.title_overlap >= VERIFIED_TITLE_OVERLAP and c.author_match
                and c.doi and not c.doi.lower().startswith(ARXIV_DOI_PREFIX)):
            return c
    if arx.venue:  # journal_ref fallback (freeform, but real)
        return arx
    return None


def _verdict_from(best: APIResult | None) -> str:
    if best is None or best.title_overlap < WEAK_TITLE_OVERLAP:
        return "not-found"
    if best.title_overlap >= VERIFIED_TITLE_OVERLAP:
        if best.author_match and (best.year_diff is None or best.year_diff <= YEAR_DRIFT_TOLERANCE):
            return "verified"
        return "metadata-drift"
    return "weak-match"


def verify_entry(entry: BibEntry, use_s2: bool = True,
                 user_agent: str = DEFAULT_USER_AGENT,
                 sleep: bool = True) -> tuple[APIResult | None, list[APIResult], str | None]:
    """Query APIs, score candidates, return (best, others, error)."""
    if not entry.title:
        return None, [], "no-title"
    candidates: list[APIResult] = []
    errored = False
    arxiv_hits = arxiv_search_metadata(entry.title, entry.first_author, user_agent)
    if sleep:
        time.sleep(ARXIV_DELAY_S)
    if arxiv_hits is None:
        errored = True
    else:
        for h in arxiv_hits:
            candidates.append(_score_candidate(entry, h, "arxiv"))
    if use_s2:
        s2_hits = semantic_scholar_search_metadata(entry.title, entry.first_author, user_agent)
        if sleep:
            time.sleep(S2_DELAY_S)
        if s2_hits is None:
            errored = True
        else:
            for h in s2_hits:
                candidates.append(_score_candidate(entry, h, "s2"))
    # OpenAlex covers all fields (journals, books, non-arXiv) — the main reason a
    # real non-CS paper would otherwise show up as "not found".
    oa_hits = openalex_search_metadata(entry.title, entry.first_author, user_agent)
    if sleep:
        time.sleep(OPENALEX_DELAY_S)
    if oa_hits is None:
        errored = True
    else:
        for h in oa_hits:
            candidates.append(_score_candidate(entry, h, "openalex"))
    # Crossref: canonical DOI registry, strong for journal/conference papers.
    cr_hits = crossref_search_metadata(entry.title, entry.first_author, user_agent)
    if sleep:
        time.sleep(CROSSREF_DELAY_S)
    if cr_hits is None:
        errored = True
    else:
        for h in cr_hits:
            candidates.append(_score_candidate(entry, h, "crossref"))
    if not candidates:
        # No candidates from any source. If a queried API actually failed (vs.
        # returning a genuine empty result), report api-error instead of
        # silently calling the entry "not found / likely fabricated".
        return None, [], ("api-error" if errored else None)
    candidates.sort(key=lambda c: -c.title_overlap)
    return candidates[0], candidates[1:5], None


def _load_cache(cache_file: Path) -> dict:
    if not cache_file.exists():
        return {}
    try:
        return json.loads(cache_file.read_text())
    except json.JSONDecodeError:
        return {}


def _save_cache(cache_file: Path, cache: dict) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2, default=str))


def _cache_matches(cached: VerifyResult, entry: BibEntry) -> bool:
    """True if a cached result still describes ``entry``'s current bib metadata.

    The cache is keyed by bib key, but a key can be re-pointed at corrected
    metadata between runs. Comparing the stored title/author/year guards against
    serving a stale verdict for an entry the user has since edited.
    """
    return (cached.bib_title == entry.title
            and cached.bib_first_author == entry.first_author
            and cached.bib_year == entry.year)


def _serialize_result(r: VerifyResult) -> dict:
    d = asdict(r)
    return d


def _deserialize_result(d: dict) -> VerifyResult:
    bm = d.get("best_match")
    om = d.get("other_matches", []) or []
    return VerifyResult(
        key=d["key"],
        bib_title=d.get("bib_title", ""),
        bib_first_author=d.get("bib_first_author", ""),
        bib_year=d.get("bib_year", ""),
        bib_pdf_present=d.get("bib_pdf_present", False),
        verdict=d.get("verdict", "not-found"),
        skip_reason=d.get("skip_reason", ""),
        best_match=APIResult(**bm) if bm else None,
        other_matches=[APIResult(**x) for x in om],
        retracted=d.get("retracted", False),
        published_match=(APIResult(**d["published_match"])
                         if d.get("published_match") else None),
    )


def verify_paper(paper_dir: Path, use_s2: bool = True, refresh: bool = False,
                 user_agent: str = DEFAULT_USER_AGENT,
                 progress: bool = True,
                 bib: str | None = None) -> list[VerifyResult]:
    """Verify every bib entry in a paper. Returns list of VerifyResult.

    ``bib`` is an optional path override (CLI flag) layered over ``refscan.json``
    and the default layout.
    """
    from .layout import resolve_layout
    layout = resolve_layout(paper_dir, bib=bib)
    bib = layout.bib
    refs = layout.refs_dir
    cache_file = layout.verify_cache
    cache = {} if refresh else _load_cache(cache_file)

    reset_rate_limit_state()
    config = load_config(paper_dir)
    import os as _os
    has_s2_key = bool(_os.environ.get(S2_API_KEY_ENV, "").strip())
    if progress and use_s2 and not has_s2_key:
        print("note: no Semantic Scholar API key in $REFSCAN_S2_API_KEY — "
              "using unauthenticated rate limit. If you hit 429 errors, "
              "S2 calls will be skipped for the rest of this run.")

    entries = parse_bib(bib)
    results: list[VerifyResult] = []
    for i, entry in enumerate(entries, 1):
        _pdf = ref_pdf_path(refs, entry.key)
        pdf_present = bool(_pdf and _pdf.exists())
        bucket = categorize(entry, pdf_present=False, config=config)  # ignore PDF for skip logic
        if bucket in ("skip-book", "skip-software"):
            results.append(VerifyResult(
                key=entry.key, bib_title=entry.title,
                bib_first_author=entry.first_author, bib_year=entry.year,
                bib_pdf_present=pdf_present, verdict="skipped",
                skip_reason=bucket,
            ))
            if progress:
                print(f"[{i}/{len(entries)}] {entry.key}: skipped ({bucket})")
            continue
        # Cache hit? Only reuse if the cached result still describes this entry's
        # current metadata — otherwise an edit to fix a title/author/year would
        # be masked by a stale verdict.
        if entry.key in cache:
            try:
                cached = _deserialize_result(cache[entry.key])
            except (KeyError, TypeError):
                cached = None
            if cached is not None and _cache_matches(cached, entry):
                results.append(cached)
                if progress:
                    print(f"[{i}/{len(entries)}] {entry.key}: cached")
                continue
        if progress:
            print(f"[{i}/{len(entries)}] {entry.key}: querying...", end=" ", flush=True)
        best, others, err = verify_entry(entry, use_s2=use_s2, user_agent=user_agent)
        if err == "no-title":
            r = VerifyResult(
                key=entry.key, bib_title=entry.title,
                bib_first_author=entry.first_author, bib_year=entry.year,
                bib_pdf_present=pdf_present, verdict="skipped",
                skip_reason="no-title",
            )
        elif err == "api-error":
            r = VerifyResult(
                key=entry.key, bib_title=entry.title,
                bib_first_author=entry.first_author, bib_year=entry.year,
                bib_pdf_present=pdf_present, verdict="api-error",
                skip_reason="API request failed",
            )
        else:
            verdict = _verdict_from(best)
            # Flag retraction when a *confident* match is marked retracted by
            # OpenAlex (orthogonal to the verdict — a retracted paper still exists).
            retracted = any(
                c is not None and c.retracted
                and c.title_overlap >= VERIFIED_TITLE_OVERLAP
                for c in [best, *others])
            published = None
            if is_preprint_citation(entry):
                published = find_published_match(
                    [c for c in [best, *others] if c is not None])
                if published is None:
                    # Candidates missed it — ask arXiv for the linked DOI.
                    published = lookup_published_version(entry,
                                                         user_agent=user_agent)
                    time.sleep(ARXIV_DELAY_S)
            r = VerifyResult(
                key=entry.key, bib_title=entry.title,
                bib_first_author=entry.first_author, bib_year=entry.year,
                bib_pdf_present=pdf_present, verdict=verdict,
                best_match=best, other_matches=others, retracted=retracted,
                published_match=published,
            )
        results.append(r)
        # Don't cache transient API failures — leave them to retry on re-run.
        if r.verdict != "api-error":
            cache[entry.key] = _serialize_result(r)
            _save_cache(cache_file, cache)  # incremental save
        if progress:
            extra = " [s2 rate-limited]" if was_rate_limited() else ""
            print(r.verdict + extra)
    return results


_VERDICT_HEADINGS = {
    "not-found": "🔴 Not found — likely fabricated",
    "weak-match": "⚠️ Weak match — verify manually",
    "metadata-drift": "🟡 Metadata drift — bib may need updating",
    "verified": "✅ Verified",
    "skipped": "⏭️ Skipped (book / software / no-title)",
    "api-error": "❌ API error",
}

_VERDICT_INSTRUCTIONS = {
    "not-found": (
        "These entries returned no convincing match from arXiv, Semantic Scholar, "
        "OpenAlex, or Crossref (which together index journals, books, conference "
        "proceedings, and preprints across all fields). Verify on Google Scholar "
        "before trusting. **If a paper does "
        "not exist, remove the citation from your bib and from any `\\cite{...}` "
        "site.** Fabricated citations are a serious research-integrity issue."
    ),
    "weak-match": (
        "API returned a related-looking paper but with significant title divergence. "
        "Could be: (a) bib metadata is wrong (update bib), (b) the API found a "
        "different paper with similar terminology (verify manually), or (c) the "
        "claimed paper is fabricated and the closest hit is unrelated."
    ),
    "metadata-drift": (
        "The right paper appears to exist, but the bib entry's author or year "
        "diverges. Update the bib to match the API result."
    ),
    "verified": "Bib metadata matches a real paper on arXiv, Semantic Scholar, or OpenAlex. No action needed.",
    "skipped": "Books, software documentation, and entries with no title are not verified by this command.",
    "api-error": "The API request failed. Re-run with `--refresh` to retry.",
}

_VERDICT_ORDER = ("not-found", "weak-match", "metadata-drift", "api-error",
                  "verified", "skipped")


def render_verification_md(paper_label: str, results: list[VerifyResult],
                            scan_date: str = "",
                            s2_rate_limited: bool = False,
                            s2_used: bool = True) -> str:
    """Format verification results as a markdown report.

    ``s2_rate_limited`` flags that Semantic Scholar returned 429 during the run.
    ``s2_used`` distinguishes ``--no-s2`` (intentional) from rate-limit fallback.
    """
    by_verdict: dict[str, list[VerifyResult]] = {}
    for r in results:
        by_verdict.setdefault(r.verdict, []).append(r)

    out = [f"# {paper_label} — Bib Verification Report\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Total bib entries: **{len(results)}**_\n")
    if not s2_used:
        out.append("_Sources queried: **arXiv + OpenAlex + Crossref** (`--no-s2`)._\n\n")
    elif s2_rate_limited:
        out.append("_Sources queried: arXiv + OpenAlex + Crossref (Semantic Scholar **rate-limited mid-run**, see caveat below)._\n\n")
    else:
        out.append("_Sources queried: arXiv + Semantic Scholar + OpenAlex + Crossref._\n\n")

    if s2_rate_limited or not s2_used:
        out.append("## ⚠️ API caveat\n\n")
        if s2_rate_limited:
            out.append("Semantic Scholar returned a 429 (rate limit) during this run, "
                       "so subsequent S2 lookups were skipped. ")
        else:
            out.append("Semantic Scholar was disabled (`--no-s2`). ")
        out.append("Entries marked **🔴 Not found** below were checked only against arXiv. "
                   "Papers that exist but are not on arXiv (typical for Nature, IEEE journals, "
                   "ACM proceedings, books) will appear as not-found here even when real. "
                   "Verify those entries on Google Scholar before treating them as fabricated.\n\n"
                   f"To raise the S2 limit, get a free API key at "
                   f"https://www.semanticscholar.org/product/api and set "
                   f"`export {S2_API_KEY_ENV}=<your-key>`, then re-run with `--refresh`.\n\n")


    retracted = [r for r in results if r.retracted]
    if retracted:
        out.append(f"## 🚨 Retracted papers ({len(retracted)})\n\n")
        out.append("**You are citing papers that OpenAlex marks as retracted.** "
                   "Retracted work should not be cited as valid evidence — review "
                   "each, and remove or replace it (or cite it explicitly as retracted). "
                   "Confirm at https://retractionwatch.com or via the journal.\n\n")
        out.append("| Key | Bib title | Best-match DOI |\n|-----|-----------|----------------|\n")
        for r in retracted:
            doi = r.best_match.doi if r.best_match else ""
            link = f"[{doi}](https://doi.org/{doi})" if doi else "—"
            out.append(f"| `{r.key}` | {r.bib_title[:70]} | {link} |\n")
        out.append("\n")

    published = [r for r in results if r.published_match]
    if published:
        out.append(f"## 📰 Published version available ({len(published)})\n\n")
        out.append("These entries cite an arXiv preprint, but a published "
                   "version exists. Consider citing the published version — "
                   "preview the upgrade with `refscan fix <paper_dir> "
                   "--upgrade-preprints`, or generate a complete entry (incl. "
                   "volume/pages) with `refscan cite <doi>`.\n\n")
        out.append("| Key | Published in | Year | DOI |\n|---|---|---|---|\n")
        for r in published:
            pm = r.published_match
            out.append(f"| `{r.key}` | {pm.venue} | {pm.year} | "
                       f"[{pm.doi}](https://doi.org/{pm.doi}) |\n")
        out.append("\n")

    out.append("## Summary\n\n| Verdict | Count |\n|---|---|\n")
    for v in _VERDICT_ORDER:
        n = len(by_verdict.get(v, []))
        if n > 0 or v in ("verified", "not-found"):
            out.append(f"| {_VERDICT_HEADINGS[v]} | {n} |\n")
    out.append("\n")

    for v in _VERDICT_ORDER:
        items = by_verdict.get(v, [])
        if not items:
            continue
        out.append(f"---\n\n## {_VERDICT_HEADINGS[v]} ({len(items)})\n\n")
        out.append(f"{_VERDICT_INSTRUCTIONS[v]}\n\n")
        for r in items:
            out.append(f"### `{r.key}`\n")
            out.append(f"- **Bib title:** {r.bib_title}\n")
            out.append(f"- **Bib author:** {r.bib_first_author}  |  "
                       f"**Bib year:** {r.bib_year}  |  "
                       f"**PDF present:** {'yes' if r.bib_pdf_present else 'no'}\n")
            if r.skip_reason:
                out.append(f"- **Skip reason:** {r.skip_reason}\n")
            if r.best_match:
                bm = r.best_match
                out.append(f"- **Best API match** ({bm.source}, "
                           f"overlap {bm.title_overlap:.0%}, "
                           f"author {'✓' if bm.author_match else '✗'}, "
                           f"year diff {bm.year_diff if bm.year_diff is not None else 'n/a'})\n")
                out.append(f"  - Title: _{bm.title}_\n")
                authors_short = ", ".join(bm.authors[:5])
                if len(bm.authors) > 5:
                    authors_short += f", … (+{len(bm.authors) - 5} more)"
                out.append(f"  - Authors: {authors_short}\n")
                if bm.arxiv_id:
                    out.append(f"  - arXiv: [{bm.arxiv_id}](https://arxiv.org/abs/{bm.arxiv_id})\n")
                if bm.doi:
                    out.append(f"  - DOI: [{bm.doi}](https://doi.org/{bm.doi})\n")
            out.append("\n")
    return "".join(out)
