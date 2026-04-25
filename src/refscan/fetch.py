"""Reference PDF fetching from arXiv and Semantic Scholar."""
from __future__ import annotations

import json
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
DEFAULT_USER_AGENT = "refscan/0.1 (+https://github.com/anthropic/refscan)"
ARXIV_DELAY_S = 3.0  # arXiv API recommends ≥3s between requests
S2_DELAY_S = 1.5     # Semantic Scholar rate limit


def _http_get(url: str, user_agent: str, timeout: int = 30) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError):
        return None


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
    data = _http_get(f"{ARXIV_API}?{params}", user_agent, timeout=20)
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
    if not title:
        return None
    q = f"{title} {author}".strip()
    params = urllib.parse.urlencode({
        "query": q,
        "fields": "title,year,authors,openAccessPdf,externalIds",
        "limit": "5",
    })
    data = _http_get(f"{S2_API}?{params}", user_agent, timeout=30)
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


def download_pdf(url: str, dest: Path, user_agent: str = DEFAULT_USER_AGENT,
                 min_bytes: int = 5000) -> bool:
    """Download a PDF URL to ``dest``. Rejects responses smaller than ``min_bytes``."""
    data = _http_get(url, user_agent, timeout=60)
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
