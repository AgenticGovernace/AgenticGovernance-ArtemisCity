"""Make the test gate enforce the bandit security policy.

Why this lives in the test suite and not only in ``make security``:

On 2026-08-17 a repo-wide formatting refactor wrapped several single-line
calls across multiple lines, which moved their trailing ``# nosec`` comments
onto the closing-paren line. Bandit attributes a finding to the line span of
the *offending expression*, not of the enclosing statement, so the
suppressions stopped applying and seven findings fired. The test gate passed
anyway, because:

- the change was semantically inert (no behavior changed, so no test could
  fail), and
- ``black --check`` still passed — the reformatted code is black-canonical.
  The formatter did not violate style, it conformed to it, and conforming is
  what orphaned the annotations.

So no existing signal could catch it. This module closes that gap: any change
that invalidates a suppression — a reformat, a moved annotation, a new finding
— now fails ``make test`` as well as ``make security``.

It also guards the gate's *scope*, which fails the same silent way. A scanned
root that stops covering tracked code does not error; it simply reports fewer
findings, and a shrinking scan is indistinguishable from a clean one at the
exit code. ``test_every_tracked_services_module_falls_under_a_scanned_root``
makes that case loud.

Note on a signal that looks useful but is not: bandit emits
``nosec encountered (BXXX), but no failed test on file <path>:<line>`` for
suppressions it considers unused. That warning also fires for suppressions
that are working correctly, whenever the finding's attributed line differs
from the annotation's line inside the same multi-line statement. It is
therefore not a reliable orphaned-suppression signal and is deliberately not
gated on here.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
PYPROJECT_CONFIG = REPO_ROOT / "pyproject.toml"

# Kept in lockstep with the `security-static` target in the root Makefile.
# A path scanned there but missing here would let a finding reach `dev` with a
# green test gate, which is the exact failure this module exists to prevent.
SCANNED_PATHS = ("src", "app", "services/mcp")


def _bandit_available() -> bool:
    """Report whether the dev-only bandit dependency is importable."""
    try:
        import bandit  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _bandit_available(),
    reason="bandit is a dev dependency; install it with `make install-dev`",
)
def test_bandit_policy_reports_no_findings_for_the_scanned_surface() -> None:
    """The reviewed bandit policy must hold across every scanned path."""
    completed = subprocess.run(  # nosec B603 - fixed argv, no untrusted input
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            *SCANNED_PATHS,
            "-c",
            "pyproject.toml",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "bandit reported findings against the reviewed policy.\n\n"
        "If a finding sits on code that carries a `# nosec` annotation, the "
        "annotation has most likely been separated from the line the finding "
        "is attributed to — commonly by the formatter wrapping a call across "
        "lines. Bandit matches `# nosec` against the line span of the "
        "offending expression, not of the enclosing statement, so the "
        "annotation must sit on the expression's own line.\n\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


@pytest.mark.skipif(
    not _bandit_available(),
    reason="bandit is a dev dependency; install it with `make install-dev`",
)
def test_bandit_policy_scans_every_path_the_makefile_scans() -> None:
    """`SCANNED_PATHS` must not drift from the Makefile's security-static target."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = next(
        line
        for line in makefile.splitlines()
        if "-m bandit -r" in line and "-c pyproject.toml" in line
    )
    scanned_in_makefile = recipe.split("-m bandit -r", 1)[1].split("-c", 1)[0].split()

    assert scanned_in_makefile == list(SCANNED_PATHS), (
        "The Makefile's security-static target and this module's SCANNED_PATHS "
        f"have drifted: Makefile scans {scanned_in_makefile}, this module "
        f"asserts {list(SCANNED_PATHS)}. Update both together."
    )


def test_bandit_policy_excludes_local_dependency_trees() -> None:
    """Bandit must not recurse into ignored environments under reviewed roots."""
    config = tomllib.loads(PYPROJECT_CONFIG.read_text(encoding="utf-8"))
    exclusions = set(config["tool"]["bandit"]["exclude_dirs"])

    required = {
        "*/.venv/*",
        "*/node_modules/*",
        "*/.pixi/*",
        "*/site-packages/*",
        "app/web/api/*",
    }
    assert required <= exclusions, (
        "Bandit walks the filesystem instead of honoring .gitignore; missing "
        f"dependency-tree exclusions: {sorted(required - exclusions)}"
    )


def _tracked_python_under(prefix: str) -> list[str]:
    """Return tracked ``.py`` paths under ``prefix`` as repo-relative posix paths."""
    completed = subprocess.run(  # nosec B603 - fixed argv, no untrusted input
        ["git", "ls-files", "--", prefix],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return sorted(
        line for line in completed.stdout.splitlines() if line.endswith(".py")
    )


def test_every_tracked_services_module_falls_under_a_scanned_root() -> None:
    """A new services/ package must join SCANNED_PATHS, not be silently skipped.

    `services/mcp` is the only scanned root naming a subdirectory rather than a
    whole top-level tree, so it is the one root a newly added sibling package
    can fall outside of. `services/prove/` and `services/cluster-starter/`
    already sit on disk as unscanned siblings; the day either becomes tracked
    runtime code, this fails and forces the scope call to be made explicitly
    instead of by omission.
    """
    tracked = _tracked_python_under("services")

    # Guard against a vacuous pass: were git to return nothing here, the
    # assertion below would hold trivially and this gate would be dead.
    assert tracked, (
        "No tracked .py files found under services/. Either the tree moved or "
        "the git query broke — this gate is only meaningful against a "
        "non-empty set."
    )

    scanned_roots = tuple(f"{path}/" for path in SCANNED_PATHS)
    unscanned = [path for path in tracked if not path.startswith(scanned_roots)]

    assert not unscanned, (
        "These tracked services/ modules fall outside every bandit root, so "
        "`make security-static` never scans them:\n  "
        + "\n  ".join(unscanned)
        + "\n\nAdd the package's root to the security-static target in the "
        "Makefile AND to SCANNED_PATHS here — they are asserted in lockstep by "
        "test_bandit_policy_scans_every_path_the_makefile_scans. Do not widen "
        "the root to a bare `services`; see the SCANNED_PATHS comment above."
    )


def _bandit_pre_commit_hook() -> dict[str, Any]:
    """Return the bandit hook block from .pre-commit-config.yaml, plus its rev."""
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        if not str(repo.get("repo", "")).rstrip("/").endswith("/bandit"):
            continue
        for hook in repo.get("hooks", []):
            if hook.get("id") == "bandit":
                return {**hook, "rev": repo["rev"]}
    raise AssertionError(
        "No bandit hook found in .pre-commit-config.yaml. It is a reviewed part "
        "of the security policy; removing it needs an explicit decision, not a "
        "silently passing test."
    )


def test_pre_commit_bandit_hook_scans_the_same_roots_as_the_makefile() -> None:
    """The commit-time scan must cover exactly the surface `make security` covers.

    A narrower hook lets a finding reach a commit that `make security-static`
    would have rejected; a wider one (notably the old ``-r .``) walks the
    gitignored vendored trees and buries the real findings.
    """
    hook = _bandit_pre_commit_hook()
    args = [str(arg) for arg in hook.get("args", [])]

    assert "-r" in args, (
        "The bandit pre-commit hook no longer passes -r, so the roots this test "
        f"exists to pin are gone. args={args}"
    )
    roots = args[args.index("-r") + 1 :]

    assert roots == list(SCANNED_PATHS), (
        "The bandit pre-commit hook and SCANNED_PATHS have drifted: the hook "
        f"scans {roots}, this module asserts {list(SCANNED_PATHS)}. The "
        "Makefile, this constant, and .pre-commit-config.yaml move together."
    )

    assert hook.get("pass_filenames") is False, (
        "The bandit pre-commit hook needs `pass_filenames: false`. Left at the "
        "default, pre-commit appends staged filenames to argv and bandit scans "
        "them in addition to the roots above — so staging one gitignored "
        "vendored file silently widens the reviewed surface."
    )


def test_pre_commit_bandit_declares_the_toml_extra_without_a_version() -> None:
    """`bandit[toml]` must be declared, and must stay unversioned.

    The version comes from `rev` alone: pre-commit builds the hook's venv from
    its own checkout. That clone is shallow and carries no tags, so
    setuptools_scm stamps the local build ``0.0.0`` — and adding a version here
    (``bandit[toml]==1.9.4``) makes pip see two irreconcilable requirements and
    refuse to install the hook at all::

        ERROR: Cannot install bandit 0.0.0 (from .../pre-commit/repo...) and
        bandit==1.9.4 because these package versions have conflicting
        dependencies.

    The extra itself is not optional — without it bandit cannot read
    ``-c pyproject.toml`` and the whole reviewed policy goes unapplied.
    """
    hook = _bandit_pre_commit_hook()
    declared = [
        str(dep)
        for dep in hook.get("additional_dependencies", [])
        if str(dep).startswith("bandit")
    ]

    assert any("[toml]" in dep for dep in declared), (
        "The bandit pre-commit hook must declare `bandit[toml]` in "
        f"additional_dependencies (got {declared}). Without the toml extra, "
        "`-c pyproject.toml` is unreadable and the reviewed policy — every "
        "exclude_dirs entry and skip — silently does not apply."
    )

    for dep in declared:
        assert not any(spec in dep for spec in ("==", ">=", "<=", "~=", "!=")), (
            f"Leave the bandit additional_dependency unversioned (got {dep!r}). "
            "pre-commit's shallow clone builds as 0.0.0, so any version "
            "specifier here conflicts with it and the hook fails to install. "
            "Change `rev` instead — that is what selects the version."
        )
