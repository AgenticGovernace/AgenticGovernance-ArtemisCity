#!/usr/bin/env python3
"""Artemis City environment setup script.

This script bootstraps the Python virtual environment, installs dependencies,
provisions the local secrets configuration, and installs TypeScript service dependencies.
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

    # The root uv lock is the single source of truth for Python dependencies.
    # This script may itself be launched by any Python, so every environment
    # operation explicitly targets the repository's Python 3.12 interpreter.
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        print("-> Installing uv")
        run_checked(
            [sys.executable, "-m", "pip", "install", "--quiet", "uv"],
            cwd=repo_root,
            operation="uv installation",
        )
        uv_executable = shutil.which("uv")
        if uv_executable is None:
            raise RuntimeError(
                "uv was installed but is not available on PATH. Restart the shell "
                "and rerun setup."
            )

    # Create virtual environment if it doesn't exist
    venv_dir = repo_root / ".venv"
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    venv_bin_path = venv_dir / bin_dir
    venv_python = venv_bin_path / ("python.exe" if os.name == "nt" else "python")
    if not venv_python.is_file():
        if venv_dir.exists():
            raise RuntimeError(
                f"The repository environment at {venv_dir} is incomplete. "
                "Run `make clean-env` and rerun setup."
            )
        print(f"-> Creating virtual environment at {venv_dir}")
        run_checked(
            [uv_executable, "venv", "--python", "3.12", str(venv_dir)],
            cwd=repo_root,
            operation="Python 3.12 virtual environment creation",
        )

    # Put the venv first for later setup subprocesses, while still passing the
    # exact interpreter to uv so nested/system environments cannot be selected.
    os.environ["VIRTUAL_ENV"] = str(venv_dir)
    os.environ["PATH"] = os.pathsep.join(
        [str(venv_bin_path), os.environ.get("PATH", "")]
    )
    if "PYTHONHOME" in os.environ:
        del os.environ["PYTHONHOME"]

    print(f"-> Installing locked Python dependencies into {venv_python}")
    run_checked(
        [
            uv_executable,
            "sync",
            "--locked",
            "--python",
            str(venv_python),
        ],
        cwd=repo_root,
        operation="locked Python dependency installation",
    )

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

    # TypeScript services setup
    mcp_server_dir = repo_root / "src" / "Artemis Agentic Memory Layer"
    if mcp_server_dir.is_dir():
        print("-> Installing Obsidian MCP server deps")
        res = subprocess.run("npm install", cwd=str(mcp_server_dir), shell=True)
        if res.returncode != 0:
            print("!! npm install failed in Artemis Agentic Memory Layer")

    frontend_dir = repo_root / "app" / "web" / "frontend"
    if frontend_dir.is_dir():
        print("-> Installing dashboard frontend deps")
        res = subprocess.run("npm install", cwd=str(frontend_dir), shell=True)
        if res.returncode != 0:
            print("!! npm install failed in app/web/frontend")

    print("==> Setup complete (see any '!!' lines above for skipped/failed steps).")
    print("    Lint/format/type-check: make check")
    print("    Run Python test suite:  make test")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"!! Setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
