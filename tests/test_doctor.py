"""Tests for refscan.doctor."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from refscan import cli
from refscan.doctor import (
    CheckResult,
    check_env,
    check_layout,
    check_network,
    check_pdftotext,
    check_python,
    check_refscan,
    check_semantic_backends,
    render,
    run_doctor,
)


def test_check_python_ok() -> None:
    r = check_python()
    assert r.status == "ok"  # the test suite itself requires 3.10+


def test_check_python_fail() -> None:
    with patch("refscan.doctor.sys") as fake_sys:
        fake_sys.version_info = (3, 9, 7)
        fake_sys.version = "3.9.7"
        r = check_python()
    assert r.status == "fail"
    assert "3.10" in r.hint


def test_check_refscan_reports_version() -> None:
    from refscan import __version__
    r = check_refscan()
    assert r.status == "info"
    assert __version__ in r.message


def test_check_pdftotext_found() -> None:
    fake = type("P", (), {"stderr": "pdftotext version 24.02.0\nCopyright ...",
                          "stdout": ""})()
    with patch("refscan.doctor.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("refscan.doctor.subprocess.run", return_value=fake):
        r = check_pdftotext()
    assert r.status == "ok"
    assert "24.02.0" in r.message


def test_check_pdftotext_missing() -> None:
    with patch("refscan.doctor.shutil.which", return_value=None):
        r = check_pdftotext()
    assert r.status == "fail"
    assert "poppler" in r.hint


def test_semantic_none_installed() -> None:
    with patch("refscan.doctor.available_backends", return_value=[]):
        r = check_semantic_backends()
    assert r.status == "warn"
    assert "semantic" in r.hint


def test_semantic_working_backend() -> None:
    with patch("refscan.doctor.available_backends", return_value=["model2vec"]), \
         patch("refscan.doctor.importlib.import_module", return_value=object()):
        r = check_semantic_backends()
    assert r.status == "ok"
    assert "model2vec" in r.message


def test_semantic_broken_backend() -> None:
    with patch("refscan.doctor.available_backends",
               return_value=["sentence-transformers"]), \
         patch("refscan.doctor.importlib.import_module",
               side_effect=ImportError("numpy ABI mismatch")):
        r = check_semantic_backends()
    assert r.status == "warn"
    assert "sentence-transformers" in r.message
    assert "model2vec" in r.hint


def test_check_network_reachable_even_on_http_error() -> None:
    with patch("refscan.doctor._http_get", return_value=(None, 429)):
        results = check_network()
    assert results and all(r.status == "ok" for r in results)


def test_check_network_unreachable() -> None:
    with patch("refscan.doctor._http_get", return_value=(None, None)):
        results = check_network()
    assert results and all(r.status == "warn" for r in results)


def test_check_env_unset_warns(monkeypatch) -> None:
    monkeypatch.delenv("REFSCAN_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("REFSCAN_S2_API_KEY", raising=False)
    results = check_env()
    assert [r.status for r in results] == ["warn", "warn"]


def test_check_env_set_ok(monkeypatch) -> None:
    monkeypatch.setenv("REFSCAN_CONTACT_EMAIL", "me@example.com")
    monkeypatch.setenv("REFSCAN_S2_API_KEY", "k")
    results = check_env()
    assert [r.status for r in results] == ["ok", "ok"]


def test_check_layout_missing_bib_fails(tmp_path: Path) -> None:
    results = check_layout(tmp_path)
    assert any(r.status == "fail" for r in results)


def test_check_layout_found(tmp_path: Path) -> None:
    (tmp_path / "paper" / "sections").mkdir(parents=True)
    (tmp_path / "paper" / "references.bib").write_text("@article{k,\n title={T},\n}\n")
    (tmp_path / "paper" / "sections" / "intro.tex").write_text("hello")
    results = check_layout(tmp_path)
    statuses = [r.status for r in results]
    assert "fail" not in statuses
    assert statuses.count("ok") >= 2  # bib + sections


def test_run_doctor_exit_codes(tmp_path: Path) -> None:
    with patch("refscan.doctor.shutil.which", return_value=None):  # pdftotext missing
        results, code = run_doctor(network=False)
    assert code == 1
    assert any(r.status == "fail" for r in results)


def test_run_doctor_no_network_skips_probes() -> None:
    with patch("refscan.doctor._http_get",
               side_effect=AssertionError("should not be called")):
        results, _ = run_doctor(network=False)
    assert all("reachable" not in r.name for r in results)


def test_render_contains_summary() -> None:
    results = [CheckResult("a", "ok", "fine"),
               CheckResult("b", "warn", "meh", hint="try X"),
               CheckResult("c", "fail", "broken", hint="fix Y")]
    out = render(results)
    assert "1 ok" in out and "1 warning" in out and "1 failure" in out
    assert "try X" in out


def test_cli_doctor_dispatch(capsys) -> None:
    rc = cli.main(["doctor", "--no-network"])
    out = capsys.readouterr().out
    assert rc in (0, 1)  # depends on host env; must not crash
    assert "ok" in out


def test_cli_doctor_paper_dir_missing_bib(tmp_path: Path, capsys) -> None:
    rc = cli.main(["doctor", str(tmp_path), "--no-network"])
    assert rc == 1
    assert "references.bib" in capsys.readouterr().out
