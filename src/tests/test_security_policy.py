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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Kept in lockstep with the `security-static` target in the root Makefile.
# A path scanned there but missing here would let a finding reach `dev` with a
# green test gate, which is the exact failure this module exists to prevent.
SCANNED_PATHS = ("src", "app", "services")


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
