#!/usr/bin/env python3
"""Artemis City environment setup script.

This script bootstraps the Python virtual environment, installs dependencies,
provisions the local secrets configuration, and installs TypeScript service dependencies.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def main():
    # Find the repository root
    try:
        repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], 
                stderr=subprocess.DEVNULL
            ).decode().strip()
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
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], 
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        branch = "unknown"
    print(f"-> Branch:    {branch}")

    # Check for uv
    has_uv = shutil.which("uv") is not None
    if not has_uv:
        print("-> Installing uv")
        # Try installing uv using current python/pip
        res = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "uv"])
        if res.returncode != 0:
            subprocess.run(["pip3", "install", "--quiet", "uv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        has_uv = shutil.which("uv") is not None
        if not has_uv:
            print("!! Could not install uv, will fall back to venv/pip")

    # Create virtual environment if it doesn't exist
    venv_dir = repo_root / ".venv"
    if not venv_dir.is_dir():
        print(f"-> Creating virtual environment at {venv_dir}")
        if has_uv:
            subprocess.run([shutil.which("uv"), "venv", "--python", "3.12", str(venv_dir)])
        else:
            # Try python3.12 or fallback python3
            res = subprocess.run(["python3.12", "-m", "venv", str(venv_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode != 0:
                res = subprocess.run(["python3", "-m", "venv", str(venv_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode != 0:
                    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)])

    # "Activate" the venv in os.environ for subsequent subprocess runs
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    venv_bin_path = venv_dir / bin_dir
    venv_python = venv_bin_path / ("python.exe" if os.name == "nt" else "python")
    
    os.environ["VIRTUAL_ENV"] = str(venv_dir)
    os.environ["PATH"] = os.pathsep.join([str(venv_bin_path), os.environ.get("PATH", "")])
    if "PYTHONHOME" in os.environ:
        del os.environ["PYTHONHOME"]

    # Recheck uv inside the activated venv
    has_uv = shutil.which("uv") is not None

    # Find requirement files
    py_reqs = []
    reqs_file = repo_root / "requirements.txt"
    reqs_dev_file = repo_root / "requirements-dev.txt"
    pyproject_file = repo_root / "pyproject.toml"

    if reqs_file.is_file():
        py_reqs.extend(["-r", str(reqs_file)])
    if reqs_dev_file.is_file():
        py_reqs.extend(["-r", str(reqs_dev_file)])

    if py_reqs:
        print(f"-> Installing Python deps: {' '.join(py_reqs)}")
        if has_uv:
            subprocess.run([shutil.which("uv"), "pip", "install"] + py_reqs)
        else:
            # Upgrade pip first, then install requirements
            subprocess.run([str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
            subprocess.run([str(venv_python), "-m", "pip", "install"] + py_reqs)
    elif pyproject_file.is_file():
        print("-> No requirements*.txt at repo root; installing from pyproject.toml instead")
        if has_uv:
            subprocess.run([shutil.which("uv"), "pip", "install", "-e", str(repo_root)])
        else:
            subprocess.run([str(venv_python), "-m", "pip", "install", "-e", str(repo_root)])
    else:
        print(f"!! No requirements.txt, requirements-dev.txt, or pyproject.toml found at {repo_root}")
        print("!! Skipping Python dependency install — check that this branch matches the expected layout")

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
                print("!! Bash not found on Windows PATH, skipping setup_secrets.sh execution.")
                res = None
        else:
            res = subprocess.run([str(setup_secrets)])
            
        if res and res.returncode != 0:
            print("!! setup_secrets.sh exited non-zero, continuing")
    else:
        print("-> No setup_secrets.sh at repo root, skipping .env provisioning")

    os.environ["ARTEMIS_ENV"] = os.environ.get("ARTEMIS_ENV", "dev")

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
    main()