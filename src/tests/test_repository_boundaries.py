"""Repository boundary characterization tests for retained legacy surfaces."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    ROOT / "docs" / "audits" / "2026-08-16-reverse-sync-72cf776-path-manifest.yaml"
)
HOLD_PATH = (
    ROOT / "docs" / "audits" / "2026-08-16-reverse-sync-72cf776-removal-hold.yaml"
)
QUARANTINE_AUDIT_PATH = (
    ROOT
    / "docs"
    / "audits"
    / "2026-08-16-reverse-sync-adjacent-current-tree-quarantine.yaml"
)
MCP_COMMON_README_PATH = ROOT / "services" / "mcp" / "common" / "README.md"
EXPECTED_MANIFEST_SHA256 = (
    "60d558d7d4f2881fed87a15d61b4ad018892aba8f2690d91f172b5be3b94914e"
)
EXPECTED_QUARANTINED_COUNT = 45
EXPECTED_QUARANTINED_LINE_SHA256 = (
    "b45297b6c2de2bf734e7cb4faee9196ab3dd0e62f5a12048502e3b26af243873"
)
EXPECTED_HELD_INTERSECTION_COUNT = 24
EXPECTED_HELD_INTERSECTION_SHA256 = (
    "759c5ae61a5cbeed8e1d6128c6130340bd269ff631391f4d18334755c25ed453"
)
EXPECTED_ADJACENT_COUNT = 21
EXPECTED_ADJACENT_LINE_SHA256 = (
    "f2d025c92661781894b085552baa798a6d18e8536dc25ca2299552cf23ce55ad"
)
FORBIDDEN_IMPORT_PREFIXES = (
    "src.Kernel.",
    "src.interface.Quantumharmony_cli",
    "artemis_mcp_common",
)
QUARANTINE_EXTRA_PATHS = (
    "src/integration/state_kernel.json",
    "src/tests/integration/test_artemis_persona 2.py",
    "tests/integration/test_artemis_persona 2.py",
    "src/interface/Quantumharmony_cli.py",
    "services/mcp/common/pyproject.toml",
    "services/mcp/common/src/artemis_mcp_common/__init__.py",
    "services/mcp/common/src/artemis_mcp_common/gate.py",
    "services/mcp/common/src/artemis_mcp_common/models.py",
    "services/mcp/common/src/artemis_mcp_common/principals.py",
    "services/mcp/common/tests/test_gate.py",
    "services/mcp/common/tests/test_models.py",
)
BYTE_IDENTICAL_DUPLICATES = {
    "src/Kernel/agent_router.py": "app/kernel/agent_router.py",
    "src/Kernel/agent_router.yaml": "app/kernel/agent_router.yaml",
    "src/Kernel/artemis_cli.py": "app/kernel/artemis_cli.py",
    "src/Kernel/cli.py": "app/kernel/cli.py",
    "src/Kernel/kernel.py": "app/kernel/kernel.py",
    "src/Kernel/memory_bus.py": "app/kernel/memory_bus.py",
    "src/Kernel/agents/__init__.py": "app/kernel/agents/__init__.py",
    "src/Kernel/agents/base.py": "app/kernel/agents/base.py",
    "src/Kernel/agents/daemon_agent.py": "app/kernel/agents/daemon_agent.py",
    "src/Kernel/agents/planner_agent.py": "app/kernel/agents/planner_agent.py",
}
PERSONA_DUPLICATES = (
    {
        "path": "src/tests/integration/test_artemis_persona 2.py",
        "canonical_peer": "src/tests/integration/test_artemis_persona.py",
    },
    {
        "path": "tests/integration/test_artemis_persona 2.py",
        "canonical_peer": "tests/integration/test_artemis_persona.py",
    },
)


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


def _tracked_paths() -> set[str]:
    return set(_git_ls_files())


def _production_python_paths() -> list[Path]:
    rel_paths = _git_ls_files("src", "app")
    paths: list[Path] = []
    for rel_path in rel_paths:
        if not rel_path.endswith(".py"):
            continue
        if "/tests/" in rel_path or rel_path.startswith("tests/"):
            continue
        paths.append(ROOT / rel_path)
    return paths


def _quarantined_payload_paths() -> list[str]:
    tracked = _tracked_paths()
    kernel_paths = sorted(path for path in tracked if path.startswith("src/Kernel/"))
    payload_paths = sorted([*kernel_paths, *QUARANTINE_EXTRA_PATHS])
    return payload_paths


def _authoritative_python_paths() -> list[Path]:
    quarantined = set(_quarantined_payload_paths())
    authoritative: list[Path] = []
    for path in _production_python_paths():
        rel_path = path.relative_to(ROOT).as_posix()
        if rel_path in quarantined:
            continue
        authoritative.append(path)
    return authoritative


def _python_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals


def _line_sha256(paths: list[str]) -> str:
    payload = "".join(f"{path}\n" for path in paths).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_yaml(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _held_manifest_paths() -> set[str]:
    manifest = _load_yaml(MANIFEST_PATH)
    manifest_paths = manifest["paths"]
    return {
        entry["path"]
        for entry in manifest_paths
        if entry["classification"] == "REMOVE_REVERSE_SYNC"
        and entry["source_status"] == "A"
    }


def _adjacent_group_paths(audit: dict[str, object]) -> list[str]:
    groups = audit["adjacent_groups"]
    flattened: list[str] = []
    for entry in groups["compatibility_facade"]:
        flattened.append(entry["path"])
    for entry in groups["lower_case_byte_identical_duplicates"]:
        flattened.append(entry["path"])
    for entry in groups["generated_integration_state"]:
        flattened.append(entry["path"])
    for entry in groups["duplicate_persona_tests"]:
        flattened.append(entry["path"])
    for entry in groups["dormant_mcp_common_incubator"]:
        flattened.append(entry["path"])
    return flattened


def _import_targets(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
    return targets


def _violation(prefix: str, detail: str) -> str:
    return f"LEGACY_QUARANTINE_VIOLATION {prefix}: {detail}"


def test_production_python_paths_include_top_level_and_nested_modules() -> None:
    rel_paths = sorted(
        path.relative_to(ROOT).as_posix() for path in _authoritative_python_paths()
    )

    assert "src/__init__.py" in rel_paths
    assert "app/__init__.py" in rel_paths
    assert "app/kernel/__init__.py" in rel_paths
    assert "src/Kernel/__init__.py" not in rel_paths
    assert "src/interface/Quantumharmony_cli.py" not in rel_paths
    assert not any("/tests/" in rel_path or rel_path.startswith("tests/") for rel_path in rel_paths)


def test_tracked_paths_do_not_casefold_collide() -> None:
    collisions: dict[str, list[str]] = defaultdict(list)
    for rel_path in _git_ls_files():
        collisions[rel_path.casefold()].append(rel_path)

    duplicates = {
        key: values for key, values in collisions.items() if len(values) > 1
    }
    assert not duplicates


def test_legacy_quarantine_audit_matches_current_tree_scope() -> None:
    tracked = _tracked_paths()
    payload_paths = _quarantined_payload_paths()
    audit = _load_yaml(QUARANTINE_AUDIT_PATH)
    hold = _load_yaml(HOLD_PATH)
    held_manifest_paths = _held_manifest_paths()
    held_payload_paths = [path for path in payload_paths if path in held_manifest_paths]
    adjacent_payload_paths = [
        path for path in payload_paths if path not in held_manifest_paths
    ]

    missing_tracked = [path for path in payload_paths if path not in tracked]
    missing_files = [path for path in payload_paths if not (ROOT / path).exists()]
    lexical_violations = [
        path
        for path in payload_paths
        if Path(path).is_absolute() or ".." in Path(path).parts
    ]
    symlink_violations = [
        path for path in payload_paths if (ROOT / path).is_symlink()
    ]

    assert "services/mcp/common/README.md" not in payload_paths
    assert len(payload_paths) == len(set(payload_paths)) == EXPECTED_QUARANTINED_COUNT, (
        _violation("payload-count", f"paths={len(payload_paths)}")
    )
    assert not missing_tracked, _violation("missing-tracked", str(missing_tracked[:5]))
    assert not missing_files, _violation("missing-files", str(missing_files[:5]))
    assert not lexical_violations, _violation("lexical-paths", str(lexical_violations[:5]))
    assert not symlink_violations, _violation("symlink-paths", str(symlink_violations[:5]))

    assert _line_sha256(payload_paths) == EXPECTED_QUARANTINED_LINE_SHA256
    assert len(held_payload_paths) == EXPECTED_HELD_INTERSECTION_COUNT
    assert _line_sha256(held_payload_paths) == EXPECTED_HELD_INTERSECTION_SHA256
    assert len(adjacent_payload_paths) == EXPECTED_ADJACENT_COUNT
    assert _line_sha256(adjacent_payload_paths) == EXPECTED_ADJACENT_LINE_SHA256

    assert audit["api_version"] == "artemis.quantumharmony.dev/v1"
    assert audit["kind"] == "LegacyQuarantineAudit"
    assert audit["metadata"]["status"] == "active"
    assert audit["source_manifest"] == {
        "path": "docs/audits/2026-08-16-reverse-sync-72cf776-path-manifest.yaml",
        "sha256": EXPECTED_MANIFEST_SHA256,
    }
    assert audit["upstream_hold"] == {
        "path": "docs/audits/2026-08-16-reverse-sync-72cf776-removal-hold.yaml",
        "status": "active",
        "preservation_statement": (
            "The 217-path hold and this adjacent quarantine are preservation "
            "records, not mutation authority."
        ),
    }
    assert hold["metadata"]["status"] == "active"

    quarantined_payloads = audit["quarantined_payloads"]
    assert quarantined_payloads["count"] == EXPECTED_QUARANTINED_COUNT
    assert quarantined_payloads["line_encoding"] == (
        "sorted UTF-8 paths, one path per line, terminal LF"
    )
    assert quarantined_payloads["line_sha256"] == EXPECTED_QUARANTINED_LINE_SHA256
    assert quarantined_payloads["held_manifest_intersection"] == {
        "count": EXPECTED_HELD_INTERSECTION_COUNT,
        "line_encoding": "sorted UTF-8 paths, one path per line, terminal LF",
        "line_sha256": EXPECTED_HELD_INTERSECTION_SHA256,
        "derivation": (
            "Intersect the 45-path quarantine scope with the active "
            "reverse-sync removal hold selection."
        ),
    }
    assert quarantined_payloads["adjacent_current_tree"] == {
        "count": EXPECTED_ADJACENT_COUNT,
        "line_encoding": "sorted UTF-8 paths, one path per line, terminal LF",
        "line_sha256": EXPECTED_ADJACENT_LINE_SHA256,
    }

    adjacent_group_paths = sorted(_adjacent_group_paths(audit))
    assert adjacent_group_paths == adjacent_payload_paths


def test_legacy_quarantine_evidence_matches_current_tree() -> None:
    audit = _load_yaml(QUARANTINE_AUDIT_PATH)
    non_authority = audit["non_authority"]
    release_enforcement = audit["release_enforcement"]
    groups = audit["adjacent_groups"]

    for duplicate_path, canonical_peer in BYTE_IDENTICAL_DUPLICATES.items():
        assert Path(ROOT / duplicate_path).read_bytes() == Path(
            ROOT / canonical_peer
        ).read_bytes()
    duplicate_pairs = {
        entry["path"]: entry["canonical_peer"]
        for entry in groups["lower_case_byte_identical_duplicates"]
    }
    assert duplicate_pairs == BYTE_IDENTICAL_DUPLICATES

    for duplicate in PERSONA_DUPLICATES:
        duplicate_path = duplicate["path"]
        canonical_peer = duplicate["canonical_peer"]
        assert (ROOT / duplicate_path).exists()
        assert (ROOT / canonical_peer).exists()
        assert Path(duplicate_path).stem.replace(" 2", "") == Path(canonical_peer).stem
    persona_pairs = {
        entry["path"]: entry["canonical_peer"]
        for entry in groups["duplicate_persona_tests"]
    }
    assert persona_pairs == {
        entry["path"]: entry["canonical_peer"] for entry in PERSONA_DUPLICATES
    }
    assert all(entry["evidence"] for entry in groups["duplicate_persona_tests"])

    parsed_state = json.loads(
        (ROOT / "src" / "integration" / "state_kernel.json").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(parsed_state, dict)
    generated_state = groups["generated_integration_state"]
    assert generated_state == [
        {
            "path": "src/integration/state_kernel.json",
            "rationale": "Generated integration history is retained for comparison only.",
        }
    ]

    compatibility = groups["compatibility_facade"]
    assert compatibility == [
        {
            "path": "src/Kernel/__init__.py",
            "import_contract": "src.Kernel is the only allowed compatibility import.",
        }
    ]

    dormant_paths = sorted(
        entry["path"] for entry in groups["dormant_mcp_common_incubator"]
    )
    assert dormant_paths == sorted(
        path
        for path in QUARANTINE_EXTRA_PATHS
        if path.startswith("services/mcp/common/")
    )

    readme_text = MCP_COMMON_README_PATH.read_text(encoding="utf-8")
    for phrase in (
        "dormant incubator",
        "not production authentication",
        "not production authorization",
        "not production routing",
        "not principal authority",
        "caller-selected capability",
        "server-owned ATP operation mapping",
        "production wiring and publication are forbidden",
        "governed-core replacement/adapters are reviewed",
    ):
        assert phrase in readme_text

    assert non_authority == {
        "authorizes_deletion": False,
        "authorizes_restore": False,
        "authorizes_move": False,
        "authorizes_rename": False,
        "authorizes_content_rewrite": False,
        "tracked_presence_grants_runtime_authority": False,
        "tracked_presence_grants_import_authority": False,
        "tracked_presence_grants_routing_authority": False,
        "tracked_presence_grants_test_authority": False,
        "tracked_presence_grants_release_authority": False,
        "allowed_compatibility_imports": ["src.Kernel"],
        "forbidden_production_import_prefixes": list(FORBIDDEN_IMPORT_PREFIXES),
        "collection_exclusions": [
            "src/tests/integration/test_artemis_persona 2.py",
            "tests/integration/test_artemis_persona 2.py",
        ],
    }
    assert release_enforcement == {
        "exact_allowlists_pending": True,
        "mcp_common_production_authority": False,
        "mcp_common_publish_authority": False,
    }
    assert audit["review_signoffs"] == []


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


def test_authoritative_python_does_not_import_quarantined_prefixes() -> None:
    violations: list[str] = []
    for path in _authoritative_python_paths():
        rel_path = path.relative_to(ROOT).as_posix()
        for target in _import_targets(path):
            if target == "src.Kernel":
                continue
            if any(
                target == prefix or target.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(f"{rel_path}:{target}")

    assert not violations, _violation("forbidden-imports", str(sorted(violations)))


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
