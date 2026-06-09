"""BibTeX parsing.

A deliberately minimal parser. Handles the subset used by typical ML/CS papers:
``@type{key, field = {value}, ...}`` with brace- or quote-delimited values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BibEntry:
    """A single BibTeX entry."""

    key: str
    entry_type: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return re.sub(r"[{}]", "", self.fields.get("title", "")).strip()

    @property
    def first_author(self) -> str:
        a = self.fields.get("author", "")
        if not a:
            return ""
        first = a.split(" and ")[0]
        if "," in first:
            last = first.split(",")[0].strip()
        else:
            toks = first.strip().split()
            last = toks[-1] if toks else ""
        return re.sub(r"[{}\\]", "", last).strip()

    @property
    def year(self) -> str:
        return self.fields.get("year", "").strip()

    @property
    def explicit_arxiv_id(self) -> str | None:
        """Return arXiv ID if one appears verbatim in any field, else None."""
        for v in self.fields.values():
            m = re.search(
                r"(?:arXiv:|arxiv\.org/abs/|arxiv preprint arXiv:)\s*(\d{4}\.\d{4,5})",
                v,
                re.IGNORECASE,
            )
            if m:
                return m.group(1)
        return None


def parse_bib(path: Path) -> list[BibEntry]:
    """Parse a bib file into BibEntry objects.

    Handles brace-matched bodies and both brace- and quote-delimited values.
    Ignores ``@comment``, ``@string``, ``@preamble`` entries.

    Note: field values are matched with one level of brace nesting (e.g.
    ``{A {Title}}``). Values nested two or more deep (``{a {b {c}}}``) are
    truncated at the inner imbalance — acceptable for this deliberately minimal
    parser, which targets the BibTeX subset typical of ML/CS papers.
    """
    raw = path.read_text()
    entries: list[BibEntry] = []
    i = 0
    while i < len(raw):
        m = re.search(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", raw[i:])
        if not m:
            break
        entry_type = m.group(1).lower()
        if entry_type in ("comment", "string", "preamble"):
            i += m.end()
            continue
        key = m.group(2)
        start = i + m.end()
        depth, j = 1, start
        while j < len(raw) and depth > 0:
            if raw[j] == "{":
                depth += 1
            elif raw[j] == "}":
                depth -= 1
            j += 1
        body = raw[start : j - 1]
        i = j
        fields: dict[str, str] = {}
        for fm in re.finditer(
            r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|\d+)",
            body,
            re.DOTALL,
        ):
            fname = fm.group(1).lower()
            fval = fm.group(2)
            if fval.startswith("{") and fval.endswith("}"):
                fval = fval[1:-1]
            elif fval.startswith('"') and fval.endswith('"'):
                fval = fval[1:-1]
            fval = re.sub(r"\s+", " ", fval).strip()
            fields[fname] = fval
        entries.append(BibEntry(key=key, entry_type=entry_type, fields=fields))
    return entries


def is_safe_key(key: str) -> bool:
    """True if ``key`` is safe to use as a flat filename component.

    Bib keys are parsed permissively (anything but commas/whitespace), so a
    hand-written or auto-generated ``.bib`` could contain a key like
    ``../../etc/foo`` that would escape the refs directory when expanded into
    ``{key}.pdf``. Reject keys containing path separators, NUL, or traversal
    components so reference paths always stay inside ``refs_dir``.
    """
    if not key or "\x00" in key or "/" in key or "\\" in key:
        return False
    if key in (".", ".."):  # traversal components Path() would treat specially
        return False
    return Path(key).name == key


def ref_pdf_path(refs_dir: Path, key: str) -> Path | None:
    """Return ``refs_dir/{key}.pdf`` for a bib key, or ``None`` if the key is
    not a safe filename component (see :func:`is_safe_key`)."""
    if not is_safe_key(key):
        return None
    return refs_dir / f"{key}.pdf"


def cited_keys(tex_files: list[Path]) -> set[str]:
    """Extract all bib keys referenced by ``\\cite*{}`` across the given tex files."""
    keys: set[str] = set()
    for f in tex_files:
        if not f.exists():
            continue
        raw = f.read_text(errors="ignore")
        for m in re.finditer(r"\\cite[pt]?\*?\{([^}]+)\}", raw):
            for k in m.group(1).split(","):
                keys.add(k.strip())
    return keys
