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


def cited_keys(sections_dir: Path, main_tex: Path | None = None) -> set[str]:
    """Extract all bib keys referenced by ``\\cite*{}`` across section tex files."""
    files = list(sections_dir.glob("*.tex"))
    if main_tex and main_tex.exists():
        files.append(main_tex)
    keys: set[str] = set()
    for f in files:
        raw = f.read_text(errors="ignore")
        for m in re.finditer(r"\\cite[pt]?\*?\{([^}]+)\}", raw):
            for k in m.group(1).split(","):
                keys.add(k.strip())
    return keys
