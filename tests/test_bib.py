"""Tests for bib parsing."""
from __future__ import annotations

from pathlib import Path

from refscan.bib import BibEntry, cited_keys, is_safe_key, parse_bib, ref_pdf_path


def test_parse_simple_entry(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """@article{Smith2020,
  author = {Smith, Jane and Doe, John},
  title = {A Title with {Special} Words},
  year = {2020},
  journal = {Nature}
}"""
    )
    entries = parse_bib(bib)
    assert len(entries) == 1
    e = entries[0]
    assert e.key == "Smith2020"
    assert e.entry_type == "article"
    assert e.title == "A Title with Special Words"
    assert e.first_author == "Smith"
    assert e.year == "2020"


def test_parse_multiple_entries(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """% Comment line
@inproceedings{Foo2019,
  author = {Foo, A.},
  title = {Paper One},
  year = {2019}
}

@book{Bar2018,
  author = {Bar, B. and Baz, C.},
  title = {Book Title},
  year = {2018}
}"""
    )
    entries = parse_bib(bib)
    assert len(entries) == 2
    assert entries[0].entry_type == "inproceedings"
    assert entries[1].entry_type == "book"


def test_explicit_arxiv_id_detected(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """@article{Qux2021,
  author = {Qux, Q.},
  title = {Preprinted Work},
  journal = {arXiv preprint arXiv:2107.12345},
  year = {2021}
}"""
    )
    entries = parse_bib(bib)
    assert entries[0].explicit_arxiv_id == "2107.12345"


def test_parse_ignores_preamble(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """@preamble{"\\newcommand{\\foo}{bar}"}
@string{nips = "NeurIPS"}
@article{Real2022,
  author = {Real, R.},
  title = {Only Entry},
  year = {2022}
}"""
    )
    entries = parse_bib(bib)
    assert len(entries) == 1
    assert entries[0].key == "Real2022"


def test_cited_keys(tmp_path: Path) -> None:
    sections = tmp_path / "sections"
    sections.mkdir()
    (sections / "intro.tex").write_text(
        "See \\cite{Foo2019} and \\citep{Bar2018, Baz2020}."
    )
    (sections / "method.tex").write_text(
        "Following \\citet{Foo2019}, we extend..."
    )
    keys = cited_keys(sections)
    assert keys == {"Foo2019", "Bar2018", "Baz2020"}


def test_is_safe_key_accepts_normal_keys() -> None:
    for k in ("Smith2020", "foo_bar", "arxiv:2107.12345", "a-b.c", "JAX"):
        assert is_safe_key(k), k


def test_is_safe_key_rejects_traversal_and_separators() -> None:
    for k in ("../etc/passwd", "..", ".", "a/b", "a\\b", "", "x\x00y", "/abs"):
        assert not is_safe_key(k), k


def test_ref_pdf_path_safe_key(tmp_path: Path) -> None:
    assert ref_pdf_path(tmp_path, "Smith2020") == tmp_path / "Smith2020.pdf"


def test_ref_pdf_path_unsafe_key_returns_none(tmp_path: Path) -> None:
    assert ref_pdf_path(tmp_path, "../../evil") is None
    # And the rejected path would indeed have escaped the refs dir.
    escaped = (tmp_path / "refs" / "../../evil.pdf").resolve()
    assert tmp_path.resolve() not in escaped.parents


def test_bibentry_first_author_styles() -> None:
    e1 = BibEntry("k", "article", {"author": "Smith, Jane"})
    e2 = BibEntry("k", "article", {"author": "Jane Smith"})
    e3 = BibEntry("k", "article", {"author": "Smith, J. and Doe, J."})
    assert e1.first_author == "Smith"
    assert e2.first_author == "Smith"
    assert e3.first_author == "Smith"
