"""Tests for the ANSI color helpers (opt-out + non-TTY behavior)."""
from __future__ import annotations

from refscan import color


def test_force_color_wraps(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    out = color.red("danger")
    assert out == "\033[31mdanger\033[0m"
    assert color.bold("x") == "\033[1mx\033[0m"


def test_no_color_returns_plain(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")  # NO_COLOR wins
    assert color.green("ok") == "ok"
    assert color.colorize("x", "red", "bold") == "x"


def test_non_tty_returns_plain(monkeypatch) -> None:
    # pytest captures stdout (not a TTY) and no FORCE_COLOR -> disabled.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert color.enabled() is False
    assert color.yellow("warn") == "warn"


def test_no_styles_is_noop(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color.colorize("plain") == "plain"
