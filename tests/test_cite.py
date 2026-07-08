"""Tests for refscan.cite."""
from __future__ import annotations

from refscan.cite import classify_identifier


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
