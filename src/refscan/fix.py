"""Apply safe metadata corrections to references.bib using verify matches.

Conservative by design: only entries whose best API match is confident
(title overlap ≥ the verified threshold) are touched, and only two low-risk
fixes are applied:

  * **add a missing DOI** — when the entry has no DOI and a confident match
    supplies one
  * **correct a drifted year** — when the entry's year disagrees with a
    confident, author-matched record

Titles and author lists are never rewritten (too easy to clobber a correct,
well-formatted entry with an API variant). All edits operate on the raw bib
text so surrounding formatting is preserved.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .bib import BibEntry
from .verify import VERIFIED_TITLE_OVERLAP, VerifyResult


@dataclass
class BibFix:
    """A single proposed field correction for one bib entry."""
    key: str
    field: str        # "doi" | "year"
    old: str          # current value, or "" if the field is absent
    new: str
    source: str       # API source that supplied the value
    reason: str       # short human description


def compute_fixes(entries: list[BibEntry],
                  results_by_key: dict[str, VerifyResult],
                  upgrade_preprints: bool = False) -> list[BibFix]:
    """Derive safe field corrections from verify results, matched by bib key.

    With ``upgrade_preprints``, entries whose verify result carries a
    ``published_match`` (a cited arXiv preprint that has since been published)
    additionally get their DOI, journal, year — and, for ``@misc`` entries,
    the entry type — pointed at the published version. Upgrade fixes supersede
    the standard doi/year fixes for the same entry.
    """
    fixes: dict[tuple[str, str], BibFix] = {}
    for e in entries:
        r = results_by_key.get(e.key)
        if r is None:
            continue
        bm = r.best_match
        if bm is not None and bm.title_overlap >= VERIFIED_TITLE_OVERLAP:
            if bm.doi and not e.doi:
                fixes[e.key, "doi"] = BibFix(e.key, "doi", "", bm.doi, bm.source,
                                             "add missing DOI")
            # Year fixes only from publication-year sources. arXiv/S2 report the
            # *preprint* submission year, which is legitimately a year before the
            # conference/journal year a bib usually cites — "correcting" toward it
            # would corrupt a correct entry. Crossref/OpenAlex give the published year.
            if (bm.year and e.year and bm.year != e.year and bm.author_match
                    and bm.source in ("crossref", "openalex")):
                fixes[e.key, "year"] = BibFix(e.key, "year", e.year, bm.year,
                                              bm.source,
                                              "year disagrees with published record")
        pm = r.published_match
        if upgrade_preprints and pm is not None:
            if pm.doi and pm.doi.lower() != e.doi.lower():
                fixes[e.key, "doi"] = BibFix(e.key, "doi", e.doi, pm.doi,
                                             pm.source, "published version DOI")
            old_journal = e.fields.get("journal", "")
            if pm.venue and pm.venue != old_journal:
                fixes[e.key, "journal"] = BibFix(e.key, "journal", old_journal,
                                                 pm.venue, pm.source,
                                                 "published venue")
            if pm.year and pm.year != e.year:
                fixes[e.key, "year"] = BibFix(e.key, "year", e.year, pm.year,
                                              pm.source, "publication year")
            if e.entry_type == "misc":
                fixes[e.key, "entry-type"] = BibFix(e.key, "entry-type", "misc",
                                                    "article", pm.source,
                                                    "upgrade preprint to article")
    return list(fixes.values())


def _find_entry(text: str, key: str) -> tuple[int, int] | None:
    """Return (fields_start, close_brace_index) for ``key``'s entry, or None.

    ``fields_start`` is just after ``@type{key,``; ``close_brace_index`` is the
    index of the entry's matching closing brace.
    """
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        if m.group(2) != key:
            continue
        start = m.end()
        depth, j = 1, start
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        return start, j - 1
    return None


def _apply_to_entry(text: str, key: str, fixes: list[BibFix]) -> str:
    """Apply ``fixes`` to ``key``'s entry within ``text``; return new text."""
    field_fixes = [f for f in fixes if f.field != "entry-type"]
    type_fix = next((f for f in fixes if f.field == "entry-type"), None)
    span = _find_entry(text, key)
    if span is None:
        return text
    fields_start, close_idx = span
    body = text[fields_start:close_idx]
    to_insert: list[BibFix] = []
    for f in field_fixes:
        pat = re.compile(r"(\b" + re.escape(f.field) + r"\s*=\s*)"
                         r"(\{[^{}]*\}|\"[^\"]*\"|\d+)", re.IGNORECASE)
        if pat.search(body):
            body = pat.sub(lambda mm: mm.group(1) + "{" + f.new + "}", body, count=1)
        else:
            to_insert.append(f)
    insertion = "".join(f"\n  {f.field} = {{{f.new}}}," for f in to_insert)
    text = text[:fields_start] + insertion + body + text[close_idx:]
    if type_fix is not None:
        # Rewrite this entry's @type{key, header (position-independent).
        text = re.sub(r"@\w+(\s*\{\s*" + re.escape(key) + r"\s*,)",
                      "@" + type_fix.new + r"\1", text, count=1)
    return text


def apply_fixes(bib_path: Path, fixes: list[BibFix]) -> int:
    """Write ``fixes`` into ``bib_path`` in place. Returns the number applied."""
    text = bib_path.read_text()
    by_key: dict[str, list[BibFix]] = defaultdict(list)
    for f in fixes:
        by_key[f.key].append(f)
    for key, kfixes in by_key.items():
        text = _apply_to_entry(text, key, kfixes)
    bib_path.write_text(text)
    return len(fixes)
