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

from .bib import BibEntry, ref_pdf_path

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_API = "https://api.openalex.org/works"
CROSSREF_API = "https://api.crossref.org/works"
UNPAYWALL_API = "https://api.unpaywall.org/v2"
DEFAULT_USER_AGENT = "refscan/0.2 (mailto:rktreddy@gmail.com)"
ARXIV_DELAY_S = 3.0  # arXiv API recommends ≥3s between requests
S2_DELAY_S = 3.0     # Semantic Scholar unauthenticated rate is strict; 3s is conservative
OPENALEX_DELAY_S = 1.0   # OpenAlex polite pool is generous; 1s is courteous
CROSSREF_DELAY_S = 1.0   # Crossref polite pool
UNPAYWALL_DELAY_S = 1.0  # Unpaywall
S2_API_KEY_ENV = "REFSCAN_S2_API_KEY"
CONTACT_EMAIL_ENV = "REFSCAN_CONTACT_EMAIL"
_DEFAULT_CONTACT_EMAIL = "rktreddy@gmail.com"


def _contact_email() -> str:
    """Contact email for API polite pools (OpenAlex ``mailto``, Unpaywall).

    Overridable via ``$REFSCAN_CONTACT_EMAIL`` so public users identify with
    their own address rather than the maintainer's.
    """
    return os.environ.get(CONTACT_EMAIL_ENV, "").strip() or _DEFAULT_CONTACT_EMAIL

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


def was_rate_limited() -> bool:
    """True if Semantic Scholar returned a 429 (rate limit) during this run."""
    return _s2_rate_limited


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
                           max_results: int = 5) -> list[dict] | None:
    """Query arXiv and return up to ``max_results`` entries as dicts.

    Each dict has: ``title``, ``authors`` (list of strings), ``year`` (str or ""),
    ``arxiv_id`` (str or "").

    Returns ``None`` if the request itself failed (network error, HTTP error,
    or unparseable response) so callers can distinguish a genuine "no results"
    (``[]``) from "we could not reach the API". An empty title also yields
    ``[]`` (nothing was asked).
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
        return None
    try:
        tree = ET.fromstring(data.decode("utf-8"))
    except ET.ParseError:
        return None
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
                                      limit: int = 5) -> list[dict] | None:
    """Query Semantic Scholar and return up to ``limit`` entries as dicts.

    Each dict has: ``title``, ``authors`` (list of strings), ``year`` (str or ""),
    ``arxiv_id`` (str or ""), ``doi`` (str or "").

    Returns ``None`` if the request itself failed (network/HTTP error or
    unparseable response). An empty title and the rate-limit skip both yield
    ``[]`` — a 429 is surfaced separately via ``_s2_rate_limited`` and is an
    intentional skip, not a hard error.
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
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return None
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


def openalex_search_metadata(title: str, author: str = "",
                              user_agent: str = DEFAULT_USER_AGENT,
                              limit: int = 5) -> list[dict] | None:
    """Query OpenAlex (~250M works, all fields) and return up to ``limit`` dicts.

    Each dict has ``title``, ``authors``, ``year``, ``arxiv_id`` (usually ""),
    ``doi``. Returns ``None`` on request failure (vs ``[]`` for no results).
    """
    if not title:
        return []
    q = f"{title} {author}".strip()
    params = urllib.parse.urlencode({
        "search": q, "per-page": limit, "mailto": _contact_email(),
    })
    data, _ = _http_get(f"{OPENALEX_API}?{params}", user_agent, timeout=30)
    if not data:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    out = []
    for w in payload.get("results", []):
        ctitle = w.get("title") or w.get("display_name") or ""
        authors = [a.get("author", {}).get("display_name", "")
                   for a in (w.get("authorships") or []) if a.get("author")]
        authors = [a for a in authors if a]
        out.append({
            "title": ctitle,
            "authors": authors,
            "year": str(w.get("publication_year") or ""),
            "arxiv_id": "",
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        })
    return out


def openalex_pdf_url(title: str, author: str = "",
                      user_agent: str = DEFAULT_USER_AGENT,
                      min_jaccard: float = 0.4) -> str | None:
    """Query OpenAlex; return a direct open-access PDF URL on confident match."""
    if not title:
        return None
    q = f"{title} {author}".strip()
    params = urllib.parse.urlencode({
        "search": q, "per-page": "5", "mailto": _contact_email(),
    })
    data, _ = _http_get(f"{OPENALEX_API}?{params}", user_agent, timeout=30)
    if not data:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    title_words = set(re.findall(r"[a-z]+", title.lower()))
    if not title_words:
        return None
    for w in payload.get("results", []):
        ctitle = (w.get("title") or "").lower()
        ctitle_words = set(re.findall(r"[a-z]+", ctitle))
        if not ctitle_words:
            continue
        jaccard = len(title_words & ctitle_words) / len(title_words | ctitle_words)
        if jaccard < min_jaccard:
            continue
        for loc_key in ("best_oa_location", "primary_location"):
            loc = w.get(loc_key) or {}
            if loc.get("pdf_url"):
                return loc["pdf_url"]
        oa = w.get("open_access") or {}
        if oa.get("oa_url"):
            return oa["oa_url"]  # may be a landing page; download_pdf sniffs %PDF
    return None


def crossref_search_metadata(title: str, author: str = "",
                              user_agent: str = DEFAULT_USER_AGENT,
                              limit: int = 5) -> list[dict] | None:
    """Query Crossref (canonical DOI registry for journals/proceedings).

    Each dict has ``title``, ``authors``, ``year``, ``arxiv_id`` (""), ``doi``.
    Returns ``None`` on request failure (vs ``[]`` for no results).
    """
    if not title:
        return []
    q = f"{title} {author}".strip()
    params = urllib.parse.urlencode({
        "query.bibliographic": q, "rows": limit, "mailto": _contact_email(),
    })
    data, _ = _http_get(f"{CROSSREF_API}?{params}", user_agent, timeout=30)
    if not data:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    out = []
    for it in payload.get("message", {}).get("items", []):
        titles = it.get("title") or []
        authors = []
        for a in it.get("author", []) or []:
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors.append(name)
        year = ""
        for key in ("issued", "published", "published-print", "published-online", "created"):
            dp = (it.get(key) or {}).get("date-parts") or []
            if dp and dp[0] and dp[0][0]:
                year = str(dp[0][0])
                break
        out.append({
            "title": titles[0] if titles else "",
            "authors": authors,
            "year": year,
            "arxiv_id": "",
            "doi": it.get("DOI", "") or "",
        })
    return out


def unpaywall_pdf_url(doi: str, user_agent: str = DEFAULT_USER_AGENT) -> str | None:
    """Given a DOI, return the best open-access PDF URL via Unpaywall, else None."""
    doi = (doi or "").strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    if not doi:
        return None
    params = urllib.parse.urlencode({"email": _contact_email()})
    data, _ = _http_get(f"{UNPAYWALL_API}/{urllib.parse.quote(doi)}?{params}",
                        user_agent, timeout=30)
    if not data:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    loc = payload.get("best_oa_location") or {}
    return loc.get("url_for_pdf") or None


def download_pdf(url: str, dest: Path, user_agent: str = DEFAULT_USER_AGENT,
                 min_bytes: int = 5000) -> bool:
    """Download a PDF URL to ``dest``.

    Rejects responses smaller than ``min_bytes`` or that don't look like a PDF
    (no ``%PDF-`` header in the first KB) — guards against saving HTML landing
    pages returned by some open-access URLs.
    """
    data, _ = _http_get(url, user_agent, timeout=60)
    if data is None or len(data) < min_bytes:
        return False
    if b"%PDF-" not in data[:1024]:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def resolve_pdf_url(entry: BibEntry, user_agent: str = DEFAULT_USER_AGENT,
                     try_s2: bool = True,
                     sleep: bool = True) -> tuple[str | None, str | None]:
    """Resolve a downloadable PDF URL for ``entry`` without downloading.

    Tries (in order): explicit arXiv ID in bib, arXiv search, Semantic Scholar,
    OpenAlex open-access PDF, and Unpaywall (when the bib entry has a DOI).
    Returns (url, source_label) or (None, None). Sleeps between API calls when
    ``sleep`` is True.
    """
    aid = entry.explicit_arxiv_id
    if aid:
        return f"https://arxiv.org/pdf/{aid}.pdf", "arxiv-explicit"

    aid = arxiv_search(entry.title, entry.first_author, user_agent)
    if sleep:
        time.sleep(ARXIV_DELAY_S)
    if aid:
        return f"https://arxiv.org/pdf/{aid}.pdf", "arxiv-search"

    if try_s2:
        pdf_url = semantic_scholar_pdf_url(entry.title, entry.first_author, user_agent)
        if sleep:
            time.sleep(S2_DELAY_S)
        if pdf_url:
            return pdf_url, "semantic-scholar"

    oa_url = openalex_pdf_url(entry.title, entry.first_author, user_agent)
    if sleep:
        time.sleep(OPENALEX_DELAY_S)
    if oa_url:
        return oa_url, "openalex"

    doi = entry.doi
    if doi:
        up_url = unpaywall_pdf_url(doi, user_agent)
        if sleep:
            time.sleep(UNPAYWALL_DELAY_S)
        if up_url:
            return up_url, "unpaywall"

    return None, None


def fetch_entry(entry: BibEntry, dest: Path, user_agent: str = DEFAULT_USER_AGENT,
                try_s2: bool = True) -> tuple[bool, str | None]:
    """Attempt to fetch ``entry`` to ``dest``. Returns (success, source_label).

    Backwards-compatible wrapper around ``resolve_pdf_url`` + ``download_pdf``.
    """
    if dest.exists():
        return True, "already-present"
    url, source = resolve_pdf_url(entry, user_agent, try_s2)
    if url and download_pdf(url, dest, user_agent):
        return True, source
    return False, None


def fetch_paper(bib_entries: list[BibEntry], refs_dir: Path,
                user_agent: str = DEFAULT_USER_AGENT,
                try_s2: bool = True, max_workers: int = 1,
                progress: bool = True) -> list[dict]:
    """Fetch PDFs for many bib entries with optional parallel downloads.

    Resolution (API search) is sequential to respect rate limits. Downloads
    happen in a ThreadPoolExecutor with ``max_workers`` threads — set to 1
    for fully sequential behavior, or 5–10 for noticeably faster bulk fetch.

    Returns a list of dicts: {key, status, source, url}.
      - status: "downloaded" | "already-present" | "not-found" |
        "download-failed" | "unsafe-key"
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    refs_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    to_download: list[tuple[BibEntry, str, str, Path]] = []

    # Phase 1: resolve URLs (sequential, rate-limited).
    for i, e in enumerate(bib_entries, 1):
        dest = ref_pdf_path(refs_dir, e.key)
        if dest is None:
            results.append({"key": e.key, "status": "unsafe-key",
                             "source": None, "url": None})
            if progress:
                print(f"[{i}/{len(bib_entries)}] {e.key}: unsafe key — skipped",
                      flush=True)
            continue
        if dest.exists():
            results.append({"key": e.key, "status": "already-present",
                             "source": None, "url": None})
            if progress:
                print(f"[{i}/{len(bib_entries)}] {e.key}: already present", flush=True)
            continue
        if progress:
            print(f"[{i}/{len(bib_entries)}] {e.key}: resolving...", end=" ", flush=True)
        url, source = resolve_pdf_url(e, user_agent, try_s2)
        if url:
            to_download.append((e, url, source, dest))
            if progress:
                print(f"→ {source}", flush=True)
        else:
            results.append({"key": e.key, "status": "not-found",
                             "source": None, "url": None})
            if progress:
                print("not found", flush=True)

    # Phase 2: parallel download.
    if to_download and progress:
        print(f"\ndownloading {len(to_download)} PDFs (max_workers={max_workers})...",
              flush=True)
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        future_to_meta = {
            ex.submit(download_pdf, url, dest, user_agent): (e, url, source, dest)
            for (e, url, source, dest) in to_download
        }
        for future in as_completed(future_to_meta):
            e, url, source, _ = future_to_meta[future]
            ok = future.result()
            results.append({
                "key": e.key,
                "status": "downloaded" if ok else "download-failed",
                "source": source,
                "url": url,
            })
            if progress:
                tag = "✓" if ok else "✗"
                print(f"  {tag} {e.key}", flush=True)

    return results
