"""Tests for refscan.cite."""
from __future__ import annotations

from refscan.cite import classify_identifier, format_entry, make_key

_META_ARXIV = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": "2017", "arxiv_id": "1706.03762",
    "doi": "10.48550/arXiv.1706.03762", "venue": "",
    "container_type": "", "primary_class": "cs.CL",
}

_META_JOURNAL = {
    "title": "Array programming with NumPy",
    "authors": ["Charles R. Harris", "K. Jarrod Millman"],
    "year": "2020", "arxiv_id": "", "doi": "10.1038/s41586-020-2649-2",
    "venue": "Nature", "container_type": "journal",
    "volume": "585", "number": "7825", "pages": "357-362", "publisher": "Springer",
}


def test_classify_bare_doi() -> None:
    assert classify_identifier("10.1038/s41586-020-2649-2") == (
        "doi", "10.1038/s41586-020-2649-2")


def test_classify_doi_url_and_prefix() -> None:
    assert classify_identifier("https://doi.org/10.1145/3292500.3330701") == (
        "doi", "10.1145/3292500.3330701")
    assert classify_identifier("doi:10.1145/3292500.3330701") == (
        "doi", "10.1145/3292500.3330701")


def test_classify_arxiv_forms() -> None:
    for raw in ("1706.03762", "arXiv:1706.03762", "1706.03762v7",
                "https://arxiv.org/abs/1706.03762",
                "https://arxiv.org/pdf/1706.03762.pdf"):
        assert classify_identifier(raw) == ("arxiv", "1706.03762"), raw


def test_classify_old_style_arxiv() -> None:
    assert classify_identifier("math.GT/0309136") == ("arxiv", "math.GT/0309136")


def test_classify_unknown() -> None:
    kind, _ = classify_identifier("attention is all you need")
    assert kind == "unknown"


def test_make_key_basic() -> None:
    assert make_key(_META_ARXIV, set()) == "vaswani2017attention"


def test_make_key_skips_stopwords_and_collides() -> None:
    assert make_key(_META_JOURNAL, set()) == "harris2020array"
    assert make_key(_META_JOURNAL, {"harris2020array"}) == "harris2020arraya"


def test_make_key_unicode_and_empty() -> None:
    meta = {"title": "Éléments d'analyse", "authors": ["Jean Dieudonné"],
            "year": "1969"}
    assert make_key(meta, set()) == "dieudonne1969elements"
    assert make_key({}, set()) == "anon"


def test_format_entry_arxiv_misc() -> None:
    out = format_entry(_META_ARXIV, "vaswani2017attention")
    assert out.startswith("@misc{vaswani2017attention,")
    assert "  eprint = {1706.03762}," in out
    assert "  archivePrefix = {arXiv}," in out
    assert "  primaryClass = {cs.CL}," in out
    assert "  doi = {10.48550/arXiv.1706.03762}," in out
    assert out.endswith("}")


def test_format_entry_journal_article() -> None:
    out = format_entry(_META_JOURNAL, "harris2020array")
    assert out.startswith("@article{harris2020array,")
    assert "  author = {Charles R. Harris and K. Jarrod Millman}," in out
    assert "  journal = {Nature}," in out
    assert "  volume = {585}," in out
    assert "  pages = {357--362}," in out  # dash normalized for BibTeX


def test_format_entry_proceedings() -> None:
    meta = dict(_META_JOURNAL, container_type="proceedings", venue="NeurIPS 2020")
    out = format_entry(meta, "k")
    assert out.startswith("@inproceedings{k,")
    assert "  booktitle = {NeurIPS 2020}," in out
