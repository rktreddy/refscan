"""Generate BibTeX entries from DOIs / arXiv IDs (``refscan cite``)."""
from __future__ import annotations

import re
import string
import sys
import unicodedata
from pathlib import Path

from .bib import BibEntry, parse_bib
from .fetch import DEFAULT_USER_AGENT

_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_ARXIV_NEW = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")
_ARXIV_OLD = re.compile(r"^([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$")


def classify_identifier(raw: str) -> tuple[str, str]:
    """Classify a user-supplied identifier as a DOI or arXiv ID.

    Returns ``(kind, normalized)`` where kind is ``"doi"``, ``"arxiv"``, or
    ``"unknown"``. Accepts bare DOIs, doi.org URLs, ``doi:`` prefixes, bare
    arXiv IDs (new and old style), ``arXiv:`` prefixes, and arxiv.org
    abs/pdf URLs. arXiv version suffixes (``v7``) are stripped.
    """
    s = raw.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    d = re.sub(r"^doi:", "", d, flags=re.IGNORECASE)
    if _DOI.match(d):
        return "doi", d
    a = re.sub(r"^https?://(www\.)?arxiv\.org/(abs|pdf)/", "", s, flags=re.IGNORECASE)
    a = re.sub(r"\.pdf$", "", a)
    a = re.sub(r"^arxiv:", "", a, flags=re.IGNORECASE)
    m = _ARXIV_NEW.match(a) or _ARXIV_OLD.match(a)
    if m:
        return "arxiv", m.group(1)
    return "unknown", s


_KEY_STOPWORDS = frozenset({
    "a", "an", "the", "on", "of", "for", "and", "or", "in", "to", "with",
    "toward", "towards", "from", "at", "by", "is", "are", "do", "does", "via",
})


def _ascii_slug(text: str) -> str:
    """Lowercased ASCII letters only (accents folded, everything else dropped)."""
    norm = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z]", "", norm.encode("ascii", "ignore").decode().lower())


def make_key(meta: dict, existing: set[str]) -> str:
    """Build a ``<surname><year><firstword>`` citation key, collision-suffixed.

    Collisions against ``existing`` get ``a``, ``b``, … then numeric suffixes.
    """
    surname = ""
    authors = meta.get("authors") or []
    if authors:
        toks = authors[0].strip().split()
        surname = _ascii_slug(toks[-1]) if toks else ""
    word = ""
    for w in re.findall(r"[^\W\d_]+", meta.get("title") or ""):
        if w.lower() not in _KEY_STOPWORDS and len(w) > 1:
            word = _ascii_slug(w)
            if word:
                break
    base = f"{surname or 'anon'}{(meta.get('year') or '').strip()}{word}"
    if base not in existing:
        return base
    for suffix in string.ascii_lowercase:
        if base + suffix not in existing:
            return base + suffix
    n = 2
    while f"{base}{n}" in existing:
        n += 1
    return f"{base}{n}"


def format_entry(meta: dict, key: str) -> str:
    """Render a metadata dict as a BibTeX entry block (no trailing newline)."""
    venue = meta.get("venue", "")
    ctype = meta.get("container_type", "")
    arxiv_id = meta.get("arxiv_id", "")
    if ctype == "journal" or (venue and not ctype and not arxiv_id):
        etype, venue_field = "article", "journal"
    elif ctype == "proceedings":
        etype, venue_field = "inproceedings", "booktitle"
    else:
        etype, venue_field = "misc", ""
    pages = re.sub(r"(?<=\d)-(?=\d)", "--", meta.get("pages", "") or "")
    fields: list[tuple[str, str]] = []
    if meta.get("authors"):
        fields.append(("author", " and ".join(meta["authors"])))
    if meta.get("title"):
        fields.append(("title", meta["title"]))
    if venue_field and venue:
        fields.append((venue_field, venue))
    for name, val in (("volume", meta.get("volume", "")),
                      ("number", meta.get("number", "")),
                      ("pages", pages),
                      ("year", meta.get("year", "")),
                      ("publisher", meta.get("publisher", ""))):
        if val:
            fields.append((name, val))
    if arxiv_id:
        fields.append(("eprint", arxiv_id))
        fields.append(("archivePrefix", "arXiv"))
        if meta.get("primary_class"):
            fields.append(("primaryClass", meta["primary_class"]))
        if etype == "misc" and venue:
            fields.append(("note", venue))
    if meta.get("doi"):
        fields.append(("doi", meta["doi"]))
    lines = [f"@{etype}{{{key},"]
    lines.extend(f"  {name} = {{{val}}}," for name, val in fields)
    lines.append("}")
    return "\n".join(lines)


def resolve_identifier(kind: str, ident: str,
                       user_agent: str = DEFAULT_USER_AGENT) -> dict | None:
    """Resolve a classified identifier to metadata.

    ``{}`` means not found; ``None`` means the source was unreachable.
    """
    from .fetch import arxiv_lookup_by_id, crossref_lookup_by_doi
    if kind == "arxiv":
        return arxiv_lookup_by_id(ident, user_agent=user_agent)
    return crossref_lookup_by_doi(ident, user_agent=user_agent)


def _find_existing(entries: list[BibEntry], meta: dict) -> BibEntry | None:
    """Return the bib entry matching ``meta`` by DOI or arXiv ID, if any."""
    doi = (meta.get("doi") or "").lower()
    aid = meta.get("arxiv_id") or ""
    for e in entries:
        if doi and e.doi.lower() == doi:
            return e
        if aid and e.explicit_arxiv_id == aid:
            return e
    return None


def cite_identifiers(identifiers: list[str], bib_path: Path | None = None,
                     add: bool = False,
                     user_agent: str = DEFAULT_USER_AGENT) -> int:
    """Resolve identifiers to BibTeX entries; print, optionally append.

    Returns 0 when everything resolved (a dedupe skip counts as success),
    1 when any identifier was unrecognized/not found, 2 when any source was
    unreachable (2 wins over 1).
    """
    entries = (parse_bib(bib_path)
               if add and bib_path is not None and bib_path.exists() else [])
    existing_keys = {e.key for e in entries}
    worst = 0
    new_blocks: list[str] = []
    for raw in identifiers:
        kind, ident = classify_identifier(raw)
        if kind == "unknown":
            print(f"error: unrecognized identifier {raw!r} (expected a DOI like "
                  "10.1234/abc or an arXiv ID like 2301.12345)", file=sys.stderr)
            worst = max(worst, 1)
            continue
        meta = resolve_identifier(kind, ident, user_agent=user_agent)
        if meta is None:
            print(f"error: {raw}: source unreachable (network/API error)",
                  file=sys.stderr)
            worst = 2
            continue
        if not meta:
            print(f"error: {raw}: not found", file=sys.stderr)
            worst = max(worst, 1)
            continue
        dup = _find_existing(entries, meta)
        if dup is not None:
            print(f"already in bib as '{dup.key}' — skipping {raw}")
            continue
        key = make_key(meta, existing_keys)
        existing_keys.add(key)
        block = format_entry(meta, key)
        print(block)
        new_blocks.append(block)
    if add and new_blocks and bib_path is not None:
        with open(bib_path, "a") as fh:
            for block in new_blocks:
                fh.write("\n" + block + "\n")
        n = len(new_blocks)
        print(f"appended {n} entr{'y' if n == 1 else 'ies'} to {bib_path}")
    return worst
