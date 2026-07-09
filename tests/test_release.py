"""Tests for release helpers — focuses on pure logic (version bump, file
edits, changelog scan) without actually invoking git or pytest."""
from __future__ import annotations

from pathlib import Path

import pytest

from refscan.release import (
    _bump_readme_pins,
    _bump_version,
    _changelog_has_version,
    _replace_version_in_file,
)


def test_bump_patch() -> None:
    assert _bump_version("0.7.0", "patch") == "0.7.1"


def test_bump_minor() -> None:
    assert _bump_version("0.7.3", "minor") == "0.8.0"


def test_bump_major() -> None:
    assert _bump_version("0.7.3", "major") == "1.0.0"


def test_bump_explicit() -> None:
    assert _bump_version("0.7.0", "1.2.3") == "1.2.3"


def test_bump_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        _bump_version("0.7.0", "garbage")


def test_bump_rejects_non_semver_explicit() -> None:
    with pytest.raises(ValueError):
        _bump_version("0.7.0", "v0.7.1")


def test_bump_rejects_malformed_current() -> None:
    with pytest.raises(ValueError):
        _bump_version("not-a-version", "patch")


def test_changelog_has_version_present(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("# Changelog\n\n## [0.8.0] - 2026-04-24\n\n- new feature\n")
    assert _changelog_has_version(cl, "0.8.0")
    assert not _changelog_has_version(cl, "0.9.0")


def test_changelog_has_version_missing_file(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    assert not _changelog_has_version(cl, "0.8.0")


def test_replace_version_in_pyproject(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text("""[project]
name = "refscan"
version = "0.7.0"
description = "thing"
""")
    ok = _replace_version_in_file(f, "0.7.0", "0.8.0",
                                    r'version\s*=\s*"0\.7\.0"')
    assert ok
    assert 'version = "0.8.0"' in f.read_text()
    # Other content untouched
    assert 'name = "refscan"' in f.read_text()


def test_replace_version_in_init(tmp_path: Path) -> None:
    f = tmp_path / "__init__.py"
    f.write_text('"""refscan."""\n\n__version__ = "0.7.0"\n')
    ok = _replace_version_in_file(f, "0.7.0", "0.8.0",
                                    r'__version__\s*=\s*"0\.7\.0"')
    assert ok
    assert '__version__ = "0.8.0"' in f.read_text()


def test_replace_version_refuses_when_no_match(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text('version = "1.0.0"\n')
    ok = _replace_version_in_file(f, "0.7.0", "0.8.0",
                                    r'version\s*=\s*"0\.7\.0"')
    assert not ok
    # File unchanged
    assert 'version = "1.0.0"' in f.read_text()


def test_replace_version_refuses_on_multiple_matches(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text('version = "0.7.0"\nold_version = "0.7.0"\n')
    ok = _replace_version_in_file(
        f, "0.7.0", "0.8.0",
        r'(?:version|old_version)\s*=\s*"0\.7\.0"',
    )
    # Two matches → refuse to edit (ambiguous)
    assert not ok


_README_WITH_PINS = """# refscan

Some prose mentioning v0.9.0 history that must not change.

```yaml
repos:
  - repo: https://github.com/rktreddy/refscan
    rev: v0.22.0            # use the latest release tag
```

```yaml
- uses: rktreddy/refscan@v0.22.0  # use the latest release tag
```
"""


def test_bump_readme_pins_updates_both(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(_README_WITH_PINS)
    assert _bump_readme_pins(readme, "0.23.0") is True
    text = readme.read_text()
    assert "rev: v0.23.0" in text
    assert "refscan@v0.23.0" in text
    assert "v0.22.0" not in text
    assert "v0.9.0 history" in text  # prose untouched


def test_bump_readme_pins_idempotent(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(_README_WITH_PINS)
    assert _bump_readme_pins(readme, "0.22.0") is False  # already current


def test_bump_readme_pins_missing_file(tmp_path: Path) -> None:
    assert _bump_readme_pins(tmp_path / "README.md", "0.23.0") is False


_CHANGELOG = """# Changelog

## [0.24.0] — 2026-07-09

### Added
- Feature A.
- Feature B.

## [0.23.0] — 2026-07-08

### Added
- Old stuff.
"""


def test_changelog_section_mid_file(tmp_path: Path) -> None:
    from refscan.release import _changelog_section
    p = tmp_path / "CHANGELOG.md"
    p.write_text(_CHANGELOG)
    body = _changelog_section(p, "0.24.0")
    assert "Feature A." in body and "Feature B." in body
    assert "Old stuff." not in body


def test_changelog_section_last(tmp_path: Path) -> None:
    from refscan.release import _changelog_section
    p = tmp_path / "CHANGELOG.md"
    p.write_text(_CHANGELOG)
    assert "Old stuff." in _changelog_section(p, "0.23.0")


def test_github_release_invokes_gh(tmp_path: Path) -> None:
    from unittest.mock import patch as _patch

    from refscan.release import _github_release
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    with _patch("refscan.release._run") as run:
        assert _github_release(tmp_path, "0.24.0") is True
    cmd = run.call_args[0][0]
    assert cmd[:3] == ["gh", "release", "create"]
    assert "v0.24.0" in cmd


def test_github_release_survives_missing_gh(tmp_path: Path) -> None:
    from unittest.mock import patch as _patch

    from refscan.release import _github_release
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    with _patch("refscan.release._run", side_effect=FileNotFoundError("gh")):
        assert _github_release(tmp_path, "0.24.0") is False
