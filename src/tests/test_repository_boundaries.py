"""Repository boundary characterization tests for the cleanup sequence."""

from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git_ls_files(*patterns: str) -> list[str]:
    command = ["git", "ls-files", *patterns]
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def _production_python_paths() -> list[Path]:
    rel_paths = _git_ls_files("src/**/*.py", "app/**/*.py")
    paths: list[Path] = []
    for rel_path in rel_paths:
        if "/tests/" in rel_path or rel_path.startswith("tests/"):
            continue
        paths.append(ROOT / rel_path)
    return paths


def _python_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals


def test_tracked_paths_do_not_casefold_collide() -> None:
    collisions: dict[str, list[str]] = defaultdict(list)
    for rel_path in _git_ls_files():
        collisions[rel_path.casefold()].append(rel_path)

    duplicates = {
        key: values for key, values in collisions.items() if len(values) > 1
    }
    assert not duplicates


def test_src_kernel_only_exposes_the_future_compatibility_facade() -> None:
    python_paths = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "Kernel").rglob("*.py")
        if "__pycache__" not in path.parts
    )

    assert python_paths == ["src/Kernel/__init__.py"], (
        "TASK_4_SRC_KERNEL_BOUNDARY: expected src/Kernel to expose only the "
        "compatibility facade, found "
        f"{python_paths}."
    )


def test_uppercase_kernel_is_already_an_identity_facade() -> None:
    from app.kernel import Kernel as CanonicalKernel
    from src.Kernel import Kernel as CompatibilityKernel

    assert CompatibilityKernel is CanonicalKernel


def test_production_modules_do_not_import_artemis_mcp_common() -> None:
    violations: list[str] = []
    for path in _production_python_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel_path = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "artemis_mcp_common" or alias.name.startswith(
                        "artemis_mcp_common."
                    ):
                        violations.append(f"{rel_path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name == "artemis_mcp_common" or module_name.startswith(
                    "artemis_mcp_common."
                ):
                    violations.append(f"{rel_path}:{module_name}")

    assert not violations


def test_runtime_identity_is_not_codex_branded() -> None:
    offenders: list[str] = []
    runtime_roots = (
        ROOT / "src" / "Kernel",
        ROOT / "src" / "interface",
        ROOT / "app" / "kernel",
    )

    for path in _production_python_paths():
        if not any(path.is_relative_to(root) for root in runtime_roots):
            continue

        rel_path = path.relative_to(ROOT).as_posix()
        lower_rel_path = rel_path.casefold()
        if "codex" in lower_rel_path:
            offenders.append(rel_path)
            continue

        string_literals = _python_string_literals(path)
        if any("codex" in literal.casefold() for literal in string_literals):
            offenders.append(rel_path)

    assert not offenders, (
        "TASK_4_CODEX_RUNTIME_IDENTITY: remove Codex-branded runtime package "
        "paths, outputs, and CLI prompts from production modules: "
        f"{sorted(offenders)}."
    )
