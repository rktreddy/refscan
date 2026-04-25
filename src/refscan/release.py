"""Maintainer-only: bump version, run tests, commit, tag, optionally push.

For releasing new versions of refscan itself. The package detects its own
source directory (works only for editable installs) and verifies that:

  * Source dir is a clean git repo on the ``main`` branch
  * Tests pass (unless ``--no-test``)
  * CHANGELOG.md already has a section for the new version

If everything checks out, it bumps the version in ``pyproject.toml`` and
``src/refscan/__init__.py``, commits both with a standard message, tags
``v{new_version}``, and (with ``--push``) pushes branch + tag.
"""
from __future__ import annotations

import dataclasses
import re
import subprocess
import sys
from pathlib import Path

from . import __version__


@dataclasses.dataclass
class ReleasePlan:
    source_dir: Path
    current_version: str
    new_version: str
    push: bool
    run_tests: bool
    dry_run: bool


def _find_source_dir() -> Path | None:
    """Locate the editable-install source directory of refscan.

    Returns the parent of ``src/`` (containing pyproject.toml) when refscan
    was installed via ``pip install -e`` or ``uv tool install --editable``.
    Returns None for non-editable installs (from PyPI/wheel).
    """
    here = Path(__file__).resolve()  # .../src/refscan/release.py
    # Walk up: refscan -> src -> repo root
    candidate = here.parent.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return None


def _bump_version(current: str, kind: str) -> str:
    """Compute next version. ``kind`` is 'patch' / 'minor' / 'major' or an
    explicit '\\d+\\.\\d+\\.\\d+' string."""
    if re.match(r"^\d+\.\d+\.\d+$", kind):
        return kind
    parts = list(map(int, current.split(".")))
    if len(parts) != 3:
        raise ValueError(f"current version {current!r} is not MAJOR.MINOR.PATCH")
    major, minor, patch = parts
    if kind == "patch":
        patch += 1
    elif kind == "minor":
        minor += 1
        patch = 0
    elif kind == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"kind must be patch/minor/major or X.Y.Z, got {kind!r}")
    return f"{major}.{minor}.{patch}"


def _run(cmd: list[str], cwd: Path, check: bool = True,
         capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture, text=True)


def _git_clean_except(source_dir: Path, allowed: set[str]) -> tuple[bool, list[str]]:
    """Return (clean, dirty_paths). 'clean' means working tree has no
    modifications outside the ``allowed`` set of file paths."""
    r = _run(["git", "status", "--porcelain"], source_dir, capture=True)
    dirty = []
    for line in r.stdout.strip().splitlines():
        # Format: " M path" or "?? path" etc
        path = line[3:].strip()
        if path not in allowed:
            dirty.append(line)
    return (not dirty, dirty)


def _git_current_branch(source_dir: Path) -> str:
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], source_dir, capture=True)
    return r.stdout.strip()


def _changelog_has_version(changelog: Path, version: str) -> bool:
    if not changelog.exists():
        return False
    return f"[{version}]" in changelog.read_text()


def _replace_version_in_file(path: Path, current: str, new: str,
                              pattern: str) -> bool:
    """Replace exactly one occurrence of ``current`` matched by ``pattern``."""
    text = path.read_text()
    rx = re.compile(pattern)
    matches = rx.findall(text)
    if len(matches) != 1:
        return False
    new_text = rx.sub(lambda m: m.group(0).replace(current, new), text, count=1)
    path.write_text(new_text)
    return True


def plan_release(kind: str, push: bool, run_tests: bool,
                 dry_run: bool) -> ReleasePlan:
    """Validate environment + compute next version. Raises on any blocker."""
    source_dir = _find_source_dir()
    if source_dir is None:
        raise RuntimeError(
            "could not locate refscan source dir. refscan release only works "
            "with editable installs (pip install -e, uv tool install --editable)."
        )
    new = _bump_version(__version__, kind)
    return ReleasePlan(
        source_dir=source_dir,
        current_version=__version__,
        new_version=new,
        push=push,
        run_tests=run_tests,
        dry_run=dry_run,
    )


def execute(plan: ReleasePlan) -> int:
    sd = plan.source_dir
    print(f"refscan release: {plan.current_version} → {plan.new_version}")
    print(f"  source dir: {sd}")
    print(f"  push: {plan.push}  |  tests: {plan.run_tests}  |  dry-run: {plan.dry_run}")

    # 1. Branch check
    branch = _git_current_branch(sd)
    if branch != "main":
        print(f"error: must release from main branch (currently on {branch})",
              file=sys.stderr)
        return 1

    # 2. Working-tree cleanliness (allow only the files we'll modify)
    will_modify = {"pyproject.toml", "src/refscan/__init__.py", "CHANGELOG.md"}
    clean, dirty = _git_clean_except(sd, will_modify)
    if not clean:
        print("error: working tree has uncommitted changes outside the version files:",
              file=sys.stderr)
        for d in dirty:
            print(f"    {d}", file=sys.stderr)
        return 1

    # 3. CHANGELOG must have an entry for the new version
    changelog = sd / "CHANGELOG.md"
    if not _changelog_has_version(changelog, plan.new_version):
        print(f"error: CHANGELOG.md has no `## [{plan.new_version}]` section. "
              f"Add release notes for the new version first.", file=sys.stderr)
        return 1

    # 4. Run tests
    if plan.run_tests:
        print("  running tests...")
        try:
            _run(["uv", "run", "--with-editable", ".", "--with", "pytest",
                  "pytest", "-q"], sd, check=True)
        except subprocess.CalledProcessError:
            print("error: tests failed; aborting release", file=sys.stderr)
            return 1
        except FileNotFoundError:
            print("warning: uv not on PATH; falling back to plain pytest", file=sys.stderr)
            try:
                _run(["pytest", "-q"], sd, check=True)
            except subprocess.CalledProcessError:
                print("error: tests failed; aborting release", file=sys.stderr)
                return 1

    if plan.dry_run:
        print("\n  [dry-run] would now:")
        print(f"    - update pyproject.toml: version → {plan.new_version}")
        print(f"    - update src/refscan/__init__.py: __version__ → {plan.new_version}")
        print(f"    - git add pyproject.toml src/refscan/__init__.py")
        print(f"    - git commit -m \"v{plan.new_version}: ...\" (you'll be prompted to write the body)")
        print(f"    - git tag -a v{plan.new_version}")
        if plan.push:
            print(f"    - git push origin main")
            print(f"    - git push origin v{plan.new_version}")
        return 0

    # 5. Bump version files
    pyproject = sd / "pyproject.toml"
    init = sd / "src" / "refscan" / "__init__.py"
    if not _replace_version_in_file(pyproject, plan.current_version,
                                      plan.new_version,
                                      r'version\s*=\s*"' + re.escape(plan.current_version) + r'"'):
        print(f"error: could not bump version in {pyproject}", file=sys.stderr)
        return 1
    if not _replace_version_in_file(init, plan.current_version, plan.new_version,
                                      r'__version__\s*=\s*"' + re.escape(plan.current_version) + r'"'):
        print(f"error: could not bump __version__ in {init}", file=sys.stderr)
        return 1
    print(f"  bumped pyproject.toml and __init__.py to {plan.new_version}")

    # 6. Git add + commit + tag
    _run(["git", "add", "pyproject.toml", "src/refscan/__init__.py"], sd)
    msg = f"v{plan.new_version}: release\n\nSee CHANGELOG.md for the full set of changes in this version."
    _run(["git", "commit", "-m", msg], sd)
    _run(["git", "tag", "-a", f"v{plan.new_version}", "-m", f"v{plan.new_version}"], sd)
    print(f"  committed and tagged v{plan.new_version}")

    # 7. Push (optional)
    if plan.push:
        print("  pushing to origin...")
        _run(["git", "push", "origin", "main"], sd)
        _run(["git", "push", "origin", f"v{plan.new_version}"], sd)
        print(f"  pushed v{plan.new_version}")
    else:
        print(f"\n  skipped push. To push manually:\n"
              f"    cd {sd}\n"
              f"    git push origin main && git push origin v{plan.new_version}")

    return 0
