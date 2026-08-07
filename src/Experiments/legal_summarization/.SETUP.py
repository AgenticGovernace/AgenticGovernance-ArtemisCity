#!/usr/bin/env python3
"""Artemis City environment setup script.

Dependency installation is owned by the root Makefile. This wrapper delegates
to that contract, provisions local secrets, and verifies the legal-evaluation
runtime without maintaining a second installer.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_checked(command: list[str], *, cwd: Path, operation: str) -> None:
    """Run a required setup step and stop instead of hiding a partial install."""
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"{operation} failed: command not found: {command[0]}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{operation} failed with exit code {exc.returncode}"
        ) from exc


def main():
    # Find the repository root
    try:
        repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        # Fallback: traverse upwards from script location to find .git or root
        current = Path(__file__).resolve().parent
        repo_root = current
        for parent in [current] + list(current.parents):
            if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
                repo_root = parent
                break

    print("==> Artemis City environment setup")
    print(f"-> Repo root: {repo_root}")

    # Display active branch
    try:
        branch = (
            subprocess.check_output(
                ["git", "branch", "--show-current"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        branch = "unknown"
    print(f"-> Branch:    {branch}")

    print("-> Installing dependencies through the root Makefile")
    run_checked(
        ["make", "install-all"],
        cwd=repo_root,
        operation="canonical dependency installation",
    )

    # Use the environment created and validated by the root Makefile.
    venv_dir = repo_root / ".venv"
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    venv_bin_path = venv_dir / bin_dir
    venv_python = venv_bin_path / ("python.exe" if os.name == "nt" else "python")
    if not venv_python.is_file():
        raise RuntimeError(f"make install-all completed without creating {venv_python}")

    # Put the venv first for later setup subprocesses, while still passing the
    # exact interpreter to uv so nested/system environments cannot be selected.
    os.environ["VIRTUAL_ENV"] = str(venv_dir)
    os.environ["PATH"] = os.pathsep.join(
        [str(venv_bin_path), os.environ.get("PATH", "")]
    )
    if "PYTHONHOME" in os.environ:
        del os.environ["PYTHONHOME"]

    # Run setup_secrets.sh
    setup_secrets = repo_root / "setup_secrets.sh"
    if setup_secrets.is_file():
        if os.name != "nt":
            try:
                subprocess.run(["chmod", "+x", str(setup_secrets)])
            except Exception:
                pass
        # Run using bash on unix, or directly on windows if possible
        if os.name == "nt":
            bash_path = shutil.which("bash")
            if bash_path:
                res = subprocess.run([bash_path, str(setup_secrets)])
            else:
                print(
                    "!! Bash not found on Windows PATH, skipping setup_secrets.sh execution."
                )
                res = None
        else:
            res = subprocess.run([str(setup_secrets)])

        if res and res.returncode != 0:
            print("!! setup_secrets.sh exited non-zero, continuing")
    else:
        print("-> No setup_secrets.sh at repo root, skipping .env provisioning")

    os.environ["ARTEMIS_ENV"] = os.environ.get("ARTEMIS_ENV", "dev")

    print("-> Verifying Hugging Face evaluation dependencies")
    run_checked(
        [
            str(venv_python),
            "-m",
            "src.Experiments.legal_summarization.main",
            "--check-dependencies",
        ],
        cwd=repo_root,
        operation="Hugging Face runtime verification",
    )

    print("==> Setup complete (see any '!!' lines above for skipped/failed steps).")
    print("    Lint/format/type-check: make check")
    print("    Run Python test suite:  make test")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"!! Setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
