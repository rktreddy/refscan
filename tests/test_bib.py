"""Tests for bib parsing."""
from __future__ import annotations

from pathlib import Path

from refscan.bib import BibEntry, cited_keys, parse_bib


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


def test_bibentry_first_author_styles() -> None:
    e1 = BibEntry("k", "article", {"author": "Smith, Jane"})
    e2 = BibEntry("k", "article", {"author": "Jane Smith"})
    e3 = BibEntry("k", "article", {"author": "Smith, J. and Doe, J."})
    assert e1.first_author == "Smith"
    assert e2.first_author == "Smith"
    assert e3.first_author == "Smith"
