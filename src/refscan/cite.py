"""Generate BibTeX entries from DOIs / arXiv IDs (``refscan cite``)."""
from __future__ import annotations

import re

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
