"""Tiny carriage-return progress bar for interactive (TTY) output."""
from __future__ import annotations

import sys


def is_tty() -> bool:
    """True if stdout is an interactive terminal (so ``\\r`` redraws make sense)."""
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def bar(current: int, total: int, label: str = "", width: int = 22) -> str:
    """Render a fixed-width progress bar string, e.g. ``resolving [███░░] 3/9``."""
    total = max(total, 1)
    frac = min(1.0, max(0.0, current / total))
    filled = round(width * frac)
    body = "█" * filled + "░" * (width - filled)
    prefix = f"{label} " if label else ""
    return f"{prefix}[{body}] {current}/{total}"
