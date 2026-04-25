"""Reference PDF fetching from arXiv and Semantic Scholar."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .bib import BibEntry

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
DEFAULT_USER_AGENT = "refscan/0.2 (mailto:rktreddy@gmail.com)"
ARXIV_DELAY_S = 3.0  # arXiv API recommends ≥3s between requests
S2_DELAY_S = 3.0     # Semantic Scholar unauthenticated rate is strict; 3s is conservative
S2_API_KEY_ENV = "REFSCAN_S2_API_KEY"

# Module-level flag: once we get a 429 from S2, stop hammering it for the rest
# of this run.
_s2_rate_limited = False


def _http_get(url: str, user_agent: str, timeout: int = 30,
              extra_headers: dict | None = None) -> tuple[bytes | None, int | None]:
    """GET ``url``, return (body, status_code). Body is None on network error."""
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except (urllib.error.URLError, TimeoutError):
        return None, None


def reset_rate_limit_state() -> None:
    """Reset the in-process rate-limit flag. Useful for tests."""
    global _s2_rate_limited
    _s2_rate_limited = False


def _s2_headers() -> dict:
    """Return Semantic Scholar headers, including API key if env var is set."""
    key = os.environ.get(S2_API_KEY_ENV, "").strip()
    if key:
        return {"x-api-key": key}
    return {}


def arxiv_search(title: str, author: str = "", user_agent: str = DEFAULT_USER_AGENT,
                 min_overlap: float = 0.7) -> str | None:
    """Search arXiv for a paper. Return arXiv ID on confident match, else None."""
    title_clean = re.sub(r"[\\$_^{}]", " ", title)
    title_clean = re.sub(r"\s+", " ", title_clean).strip()
    if not title_clean:
        return None
    q_parts = [f'ti:"{title_clean[:120]}"']
    if author:
        q_parts.append(f"au:{author}")
    params = urllib.parse.urlencode({"search_query": " AND ".join(q_parts), "max_results": 3})
    data, _ = _http_get(f"{ARXIV_API}?{params}", user_agent, timeout=20)
    if not data:
        return None
    try:
        tree = ET.fromstring(data.decode("utf-8"))
    except ET.ParseError:
        return None
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_words = set(re.findall(r"[a-z]+", title_clean.lower()))
    if not title_words:
        return None
    for entry in tree.findall("atom:entry", ns):
        atitle_el = entry.find("atom:title", ns)
        aid_el = entry.find("atom:id", ns)
        if atitle_el is None or aid_el is None or not atitle_el.text:
            continue
        atitle = re.sub(r"\s+", " ", atitle_el.text).strip().lower()
        atitle_words = set(re.findall(r"[a-z]+", atitle))
        if not atitle_words:
            continue
        if len(title_words & atitle_words) / len(title_words) >= min_overlap:
            m = re.search(r"abs/(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})", aid_el.text.strip())
            if m:
                return m.group(1)
    return None


def semantic_scholar_pdf_url(title: str, author: str = "",
                              user_agent: str = DEFAULT_USER_AGENT,
                              min_jaccard: float = 0.4) -> str | None:
    """Query Semantic Scholar. Return a direct PDF URL if open-access, else None."""
    global _s2_rate_limited
    if not title or _s2_rate_limited:
        return None
    q = f"{title} {author}".strip()
    params = urllib.parse.urlencode({
        "query": q,
        "fields": "title,year,authors,openAccessPdf,externalIds",
        "limit": "5",
    })
    data, status = _http_get(f"{S2_API}?{params}", user_agent, timeout=30,
                              extra_headers=_s2_headers())
    if status == 429:
        _s2_rate_limited = True
        return None
    if not data:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    title_words = set(re.findall(r"[a-z]+", title.lower()))
    if not title_words:
        return None
    for c in payload.get("data", []):
        ctitle = (c.get("title") or "").lower()
        ctitle_words = set(re.findall(r"[a-z]+", ctitle))
        if not ctitle_words:
            continue
        jaccard = len(title_words & ctitle_words) / len(title_words | ctitle_words)
        if jaccard < min_jaccard:
            continue
        pdf = c.get("openAccessPdf") or {}
        if pdf.get("url"):
            return pdf["url"]
        ext = c.get("externalIds") or {}
        if ext.get("ArXiv"):
            return f"https://arxiv.org/pdf/{ext['ArXiv']}.pdf"
    return None


def arxiv_search_metadata(title: str, author: str = "",
                           user_agent: str = DEFAULT_USER_AGENT,
                           max_results: int = 5) -> list[dict]:
    """Query arXiv and return up to ``max_results`` entries as dicts.

    Each dict has: ``title``, ``authors`` (list of strings), ``year`` (str or ""),
    ``arxiv_id`` (str or "").
    """
    title_clean = re.sub(r"[\\$_^{}]", " ", title)
    title_clean = re.sub(r"\s+", " ", title_clean).strip()
    if not title_clean:
        return []
    q_parts = [f'ti:"{title_clean[:120]}"']
    if author:
        q_parts.append(f"au:{author}")
    params = urllib.parse.urlencode({
        "search_query": " AND ".join(q_parts),
        "max_results": max_results,
    })
    data, _ = _http_get(f"{ARXIV_API}?{params}", user_agent, timeout=20)
    if not data:
        return []
    try:
        tree = ET.fromstring(data.decode("utf-8"))
    except ET.ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in tree.findall("atom:entry", ns):
        atitle_el = entry.find("atom:title", ns)
        aid_el = entry.find("atom:id", ns)
        published_el = entry.find("atom:published", ns)
        author_els = entry.findall("atom:author", ns)
        if atitle_el is None or aid_el is None or not atitle_el.text:
            continue
        atitle = re.sub(r"\s+", " ", atitle_el.text).strip()
        authors = []
        for ae in author_els:
            name_el = ae.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())
        year = ""
        if published_el is not None and published_el.text:
            year_match = re.match(r"(\d{4})", published_el.text)
            if year_match:
                year = year_match.group(1)
        m = re.search(r"abs/(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})", aid_el.text.strip())
        arxiv_id = m.group(1) if m else ""
        out.append({"title": atitle, "authors": authors, "year": year,
                    "arxiv_id": arxiv_id})
    return out


def semantic_scholar_search_metadata(title: str, author: str = "",
                                      user_agent: str = DEFAULT_USER_AGENT,
                                      limit: int = 5) -> list[dict]:
    """Query Semantic Scholar and return up to ``limit`` entries as dicts.

    Each dict has: ``title``, ``authors`` (list of strings), ``year`` (str or ""),
    ``arxiv_id`` (str or ""), ``doi`` (str or "").
    """
    global _s2_rate_limited
    if not title or _s2_rate_limited:
        return []
    q = f"{title} {author}".strip()
    params = urllib.parse.urlencode({
        "query": q,
        "fields": "title,year,authors,externalIds",
        "limit": str(limit),
    })
    data, status = _http_get(f"{S2_API}?{params}", user_agent, timeout=30,
                              extra_headers=_s2_headers())
    if status == 429:
        _s2_rate_limited = True
        return []
    if not data:
        return []
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return []
    out = []
    for c in payload.get("data", []):
        ctitle = c.get("title") or ""
        author_objs = c.get("authors") or []
        authors = [a.get("name", "") for a in author_objs if a.get("name")]
        year = str(c.get("year") or "")
        ext = c.get("externalIds") or {}
        out.append({
            "title": ctitle,
            "authors": authors,
            "year": year,
            "arxiv_id": ext.get("ArXiv") or "",
            "doi": ext.get("DOI") or "",
        })
    return out


def download_pdf(url: str, dest: Path, user_agent: str = DEFAULT_USER_AGENT,
                 min_bytes: int = 5000) -> bool:
    """Download a PDF URL to ``dest``. Rejects responses smaller than ``min_bytes``."""
    data, _ = _http_get(url, user_agent, timeout=60)
    if data is None or len(data) < min_bytes:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def fetch_entry(entry: BibEntry, dest: Path, user_agent: str = DEFAULT_USER_AGENT,
                try_s2: bool = True) -> tuple[bool, str | None]:
    """Attempt to fetch ``entry`` to ``dest``. Returns (success, source_label)."""
    if dest.exists():
        return True, "already-present"

    aid = entry.explicit_arxiv_id
    if aid:
        if download_pdf(f"https://arxiv.org/pdf/{aid}.pdf", dest, user_agent):
            return True, "arxiv-explicit"

    aid = arxiv_search(entry.title, entry.first_author, user_agent)
    time.sleep(ARXIV_DELAY_S)
    if aid:
        if download_pdf(f"https://arxiv.org/pdf/{aid}.pdf", dest, user_agent):
            return True, "arxiv-search"

    if try_s2:
        pdf_url = semantic_scholar_pdf_url(entry.title, entry.first_author, user_agent)
        time.sleep(S2_DELAY_S)
        if pdf_url and download_pdf(pdf_url, dest, user_agent):
            return True, "semantic-scholar"

    return False, None
