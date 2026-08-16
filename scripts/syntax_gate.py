"""Lightweight AST syntax guard for CI promotion linting.

This keeps malformed Python files from reaching ruff/routing checks by running
before the existing lint command.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _python_sources(paths: list[Path]) -> list[Path]:
    files: list[Path] = []

    for path in paths:
        if path.is_dir():
            files.extend(path.rglob("*.py"))
            continue

        files.append(path)

    return files


def main() -> int:
    targets = [Path("src"), Path("app/api/main.py")]
    failures: list[str] = []

    for path in _python_sources(targets):
        if "__pycache__" in path.parts:
            continue

        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path}:{exc.lineno}:{exc.offset} {exc.msg}")
        except OSError as exc:
            failures.append(f"{path}: IO/read error: {exc}")

    if failures:
        print("Syntax check failed:")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("AST syntax gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
