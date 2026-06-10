"""Optional semantic / near-duplicate scan (paraphrase detection).

The exact-shingle scan (`refscan scan`) catches verbatim and lightly-edited
copying but misses paraphrase — the same idea in different words. This module
compares *sentence embeddings* so semantically close passages are flagged even
when no long run of words is shared.

Requires the optional extra::

    pip install 'refscan[semantic]'      # pulls sentence-transformers

The base package never imports the heavy deps; they load lazily inside
:func:`get_embedder`. The matching core (:func:`semantic_findings`) is pure
Python and uses NumPy only when it's already available (for speed).
"""
from __future__ import annotations

import importlib.util
import re

DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_THRESHOLD = 0.75


def available() -> bool:
    """True if the optional embedding backend is installed."""
    return importlib.util.find_spec("sentence_transformers") is not None


def get_embedder(model_name: str = DEFAULT_MODEL):
    """Return ``embed(texts) -> vectors`` (L2-normalized), or raise ImportError.

    Vectors may be a NumPy array or a list of lists; :func:`semantic_findings`
    handles either.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as ex:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "semantic scan needs extra deps: pip install 'refscan[semantic]'") from ex
    model = SentenceTransformer(model_name)

    def embed(texts):
        return model.encode(list(texts), convert_to_numpy=True,
                            normalize_embeddings=True, show_progress_bar=False)

    return embed


def split_sentences(text: str, min_words: int = 6) -> list[str]:
    """Split ``text`` into sentences (case-agnostic), keeping ones long enough."""
    out = []
    for p in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")):
        p = p.strip()
        if len(p.split()) >= min_words:
            out.append(p)
    return out


def _best_matches(paper_vecs, ref_vecs) -> list[tuple[int, float]]:
    """For each paper vector, return (best_ref_index, cosine). NumPy if available."""
    if not len(paper_vecs) or not len(ref_vecs):
        return []
    try:
        import numpy as np
        P = np.asarray(paper_vecs, dtype=float)
        R = np.asarray(ref_vecs, dtype=float)
        sims = P @ R.T
        idx = sims.argmax(axis=1)
        val = sims[np.arange(len(P)), idx]
        return list(zip(idx.tolist(), val.tolist()))
    except ImportError:
        out = []
        for pv in paper_vecs:
            best_i, best_s = -1, -1.0
            for j, rv in enumerate(ref_vecs):
                s = sum(a * b for a, b in zip(pv, rv))
                if s > best_s:
                    best_s, best_i = s, j
            out.append((best_i, best_s))
        return out


def semantic_findings(paper_units: list[tuple[str, str]],
                      ref_units: list[tuple[str, str]], embed,
                      threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Find paper sentences semantically close to a reference sentence.

    ``paper_units`` is ``[(section, sentence), ...]``; ``ref_units`` is
    ``[(bibkey, sentence), ...]``. Returns findings sorted by similarity desc.
    """
    if not paper_units or not ref_units:
        return []
    paper_vecs = embed([s for _, s in paper_units])
    ref_vecs = embed([s for _, s in ref_units])
    findings = []
    for (sec, p_sent), (j, sim) in zip(paper_units, _best_matches(paper_vecs, ref_vecs)):
        if j < 0 or sim < threshold:
            continue
        bibkey, r_sent = ref_units[j]
        findings.append({
            "section": sec, "bibkey": bibkey,
            "similarity": round(float(sim), 4),
            "paper_sentence": p_sent, "ref_sentence": r_sent,
        })
    findings.sort(key=lambda f: -f["similarity"])
    return findings


def render_semantic_md(paper_label: str, findings: list[dict], *,
                       threshold: float, scan_date: str = "",
                       max_show: int = 40) -> str:
    """Format semantic findings as a markdown report."""
    out = [f"# Semantic Scan — {paper_label}\n"]
    if scan_date:
        out.append(f"_Scan date: {scan_date}_\n")
    out.append(f"_Cosine similarity threshold: {threshold}_\n\n")
    if not findings:
        out.append("✅ No paraphrase above the similarity threshold.\n")
        return "".join(out)
    out.append(f"**{len(findings)} sentence(s)** are semantically close to a cited "
               "reference. High similarity with *different wording* can indicate "
               "paraphrase that tracks the source too closely — review and rewrite, "
               "or quote with attribution.\n\n")
    for f in findings[:max_show]:
        out.append(f"### {f['similarity']:.2f} — `{f['bibkey']}` "
                   f"(section `{f['section']}`)\n\n")
        out.append(f"- Paper: {f['paper_sentence']}\n")
        out.append(f"- Ref:   {f['ref_sentence']}\n\n")
    if len(findings) > max_show:
        out.append(f"_…and {len(findings) - max_show} more._\n")
    return "".join(out)
