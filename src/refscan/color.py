"""Minimal ANSI color helpers.

Colors are emitted only when output is a real terminal and the user hasn't
opted out. Respects the ``NO_COLOR`` convention (https://no-color.org) and a
``FORCE_COLOR`` override (useful for CI logs and tests). When disabled, every
helper returns its input unchanged, so call sites need no branching.
"""
from __future__ import annotations

import os
import sys

_CODES = {"red": "31", "green": "32", "yellow": "33", "blue": "34",
          "bold": "1", "dim": "2"}


def enabled() -> bool:
    """True if ANSI color should be emitted on stdout right now."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(sys.stdout, "isatty", lambda: False)()) \
        and os.environ.get("TERM") != "dumb"


def colorize(text: str, *styles: str) -> str:
    """Wrap ``text`` in the given ANSI ``styles`` (e.g. "red", "bold")."""
    if not styles or not enabled():
        return text
    codes = ";".join(_CODES[s] for s in styles if s in _CODES)
    return f"\033[{codes}m{text}\033[0m" if codes else text


def green(t: str) -> str:
    return colorize(t, "green")


def red(t: str) -> str:
    return colorize(t, "red")


def yellow(t: str) -> str:
    return colorize(t, "yellow")


def bold(t: str) -> str:
    return colorize(t, "bold")


def dim(t: str) -> str:
    return colorize(t, "dim")
