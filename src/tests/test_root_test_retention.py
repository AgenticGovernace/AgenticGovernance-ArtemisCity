"""Retention and collection gates for the preserved root tests tree."""

from __future__ import annotations

import ast
import copy
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "docs" / "audits" / "2026-08-16-root-test-tree-retention.yaml"
QUARANTINE_AUDIT_PATH = (
    ROOT
    / "docs"
    / "audits"
    / "2026-08-16-reverse-sync-adjacent-current-tree-quarantine.yaml"
)
SNAPSHOT_COMMIT = "ecd1cdcd1b5801e0869aca817d695ebe1d222943"
TASK_BASE_COMMIT = "9acb701727a9b855a9d7f281cd07873cdcf1dddf"
EXPECTED_ALL_ROOT_COUNT = 64
EXPECTED_ALL_ROOT_SHA = "426986bc9b60dbd4266f1d09cf76ee8656ad0b6dc598d2a812ffb5515ef80f60"
EXPECTED_DUPLICATE_COUNT = 54
EXPECTED_DUPLICATE_SHA = "ac2f338db44b5c797edad0d6de8c39844bd0a85e99bd827f5168e5c2de5a53f2"
EXPECTED_REVIEW_COUNT = 5
EXPECTED_REVIEW_SHA = "bbc1cdb563dbe89421647f1ce14e6ed16e894a2faa2010a906375e356a3ba895"
EXPECTED_INERT_COUNT = 5
EXPECTED_INERT_SHA = "3e4700bf490c861c3591b71cccc8f4fa7e85d20d6deb9547cc97d4b9b5291aea"
EXPECTED_ROOT_DEFS = 1011
EXPECTED_MATCHES = 934
EXPECTED_RAW_GAP_COUNT = 77
EXPECTED_RAW_GAP_SHA = "bcd12e5f7670a9f050e225ed494c416db5e7b8e0f6f77a671938a9c15c52fdb6"
EXPECTED_RETIRED_COUNT = 8
EXPECTED_RETIRED_SHA = "ff6613e7bd71b362ff811c4b590a9054232e1480bbe723507be2b1e81fd4e79b"
EXPECTED_REVIEW_QUEUE_COUNT = 69
EXPECTED_REVIEW_QUEUE_SHA = "44ed874a4f0152ff65a8ccf92b67a02200795e0d0d4fda5d2372ca3adea8e823"
EXPECTED_DIVERGENCE_COUNT = 18
EXPECTED_DIVERGENCE_SHA = (
    "75c127e9281bd7da8f919be24da70ec946bdc8ac5e3f91346a58a84532a32704"
)
EXPECTED_COLLECTION_ERROR_COUNT = 2
EXPECTED_COLLECTION_ERROR_SHA = (
    "e7ff932f982c0136366ef8da09c3a0fbe9c852d92b68d01310c0c84d68d2d4f6"
)
AFFECTED_COLLECTION_MODULES = {
    "src/tests/test_instruction_coverage.py",
    "src/tests/test_instruction_loader.py",
}
AUDITED_TASK5_PARENT_COMMIT = (
    "7ec7e63d4f030b95bc90aea1dbf1fa05ca38dc99"
)
AUDITED_TASK5_COMMIT = "f2623a2f13a63b4849c8aa9522a055c012b0b948"
EXPECTED_SEMANTIC_COUNTS = {
    "covered_by_current_contract": 27,
    "retired_or_superseded": 36,
    "missing_current_contract_intent": 6,
}
EXPECTED_SOURCE_COUNTS = {
    "governance": {
        "covered_by_current_contract": 8,
        "retired_or_superseded": 14,
        "missing_current_contract_intent": 0,
    },
    "hebbian": {
        "covered_by_current_contract": 7,
        "retired_or_superseded": 10,
        "missing_current_contract_intent": 2,
    },
    "memory": {
        "covered_by_current_contract": 5,
        "retired_or_superseded": 4,
        "missing_current_contract_intent": 2,
    },
    "sandbox": {
        "covered_by_current_contract": 7,
        "retired_or_superseded": 6,
        "missing_current_contract_intent": 2,
    },
    "llm": {
        "covered_by_current_contract": 0,
        "retired_or_superseded": 2,
        "missing_current_contract_intent": 0,
    },
}
INERT_ROOT_PATHS = {
    "tests/README.md",
    "tests/conftest.py",
    "tests/integration/test_artemis_persona 2.py",
    "tests/test_hebbian_marketplace_vs_inference.ipynb",
    "tests/test_hebbian_scoped_vs_coldstart.ipynb",
}
REVIEW_ROOT_PATHS = {
    "tests/integration/test_governance.py",
    "tests/integration/test_hebbian_sync.py",
    "tests/integration/test_memory_decay.py",
    "tests/integration/test_sandbox.py",
    "tests/test_llm_agent.py",
}
RETIRED_DATACLASS_IDENTITIES = {
    "src/tests/integration/test_hebbian_sync.py::TestBatchResult::test_batch_result_creation",
    "src/tests/integration/test_hebbian_sync.py::TestBatchResult::test_batch_result_to_dict",
    "src/tests/integration/test_hebbian_sync.py::TestWeightUpdate::test_weight_update_creation",
    "src/tests/integration/test_hebbian_sync.py::TestWeightUpdate::test_weight_update_defaults",
    "src/tests/integration/test_hebbian_sync.py::TestWeightUpdate::test_weight_update_to_dict",
    "src/tests/integration/test_memory_decay.py::TestDecayEvent::test_event_creation",
    "src/tests/integration/test_memory_decay.py::TestDecayEvent::test_event_to_dict",
    "src/tests/integration/test_memory_decay.py::TestMemoryNode::test_node_to_dict",
}
TARGET_TESTS = {
    (
        "src/tests/integration/test_hebbian_sync.py::TestHebbianSyncService::"
        "test_propagate_returns_true_when_auto_flush_triggers"
    ),
    (
        "src/tests/integration/test_hebbian_sync.py::TestHebbianSyncService::"
        "test_flush_with_failing_sink_is_non_fatal_and_reports_zero_applied"
    ),
    (
        "src/tests/integration/test_memory_decay.py::TestMemoryDecayService::"
        "test_restore_node_ignores_sink_failures"
    ),
    (
        "src/tests/integration/test_memory_decay.py::TestMemoryDecayService::"
        "test_provenance_write_oserror_is_non_fatal"
    ),
    (
        "src/tests/test_agent_governance.py::TestViolations::"
        "test_agent_records_expose_governance_status_partition"
    ),
}
OWNED_CANONICAL_TESTS = [
    ROOT / "src/tests/integration/test_hebbian_sync.py",
    ROOT / "src/tests/integration/test_memory_decay.py",
    ROOT / "src/tests/test_agent_governance.py",
]


def _load_audit() -> dict[str, object]:
    return yaml.safe_load(AUDIT_PATH.read_text(encoding="utf-8"))


def _collection_exclusions() -> set[str]:
    quarantine = yaml.safe_load(
        QUARANTINE_AUDIT_PATH.read_text(encoding="utf-8")
    )
    return set(quarantine["non_authority"]["collection_exclusions"])


def _canonical_line_sha(items: list[str]) -> str:
    payload = "".join(f"{item}\n" for item in sorted(items)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _tracked_paths(prefix: str) -> list[str]:
    return [line for line in _run_git("ls-files", prefix).splitlines() if line]


def _git_blob(revision: str, path: str) -> str:
    return _run_git("show", f"{revision}:{path}")


def _strip_leading_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return body[1:]
    return body


def _normalized_function_dump(node: ast.AST) -> str:
    clone = copy.deepcopy(node)
    clone.body = _strip_leading_docstring(list(clone.body))  # type: ignore[attr-defined]
    for subnode in ast.walk(clone):
        for attr in ("lineno", "end_lineno", "col_offset", "end_col_offset"):
            if hasattr(subnode, attr):
                setattr(subnode, attr, None)
    return ast.dump(clone, include_attributes=False)


def _extract_test_identities(relative_path: str, source: str) -> list[tuple[str, str]]:
    tree = ast.parse(source, filename=relative_path)
    identities: list[tuple[str, str]] = []

    def walk(nodes: list[ast.stmt], classes: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                walk(node.body, classes + [node.name])
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test")
            ):
                qualified = f"src/{relative_path}::" + "::".join(classes + [node.name])
                identities.append((qualified, _normalized_function_dump(node)))

    walk(tree.body, [])
    return identities


def _audited_identity_sets() -> dict[str, object]:
    root_paths = [
        path
        for path in _run_git("ls-tree", "-r", "--name-only", SNAPSHOT_COMMIT, "tests").splitlines()
        if path.startswith("tests/") and path.endswith(".py") and path not in INERT_ROOT_PATHS
    ]
    base_paths = [
        path
        for path in _run_git(
            "ls-tree",
            "-r",
            "--name-only",
            TASK_BASE_COMMIT,
            "src/tests",
        ).splitlines()
        if path.endswith(".py")
    ]

    base_map: dict[str, str] = {}
    for path in base_paths:
        for identity, body in _extract_test_identities(
            path.removeprefix("src/"),
            _git_blob(TASK_BASE_COMMIT, path),
        ):
            base_map[identity] = body

    root_identities: list[str] = []
    raw_gaps: list[str] = []
    divergences: list[tuple[str, str]] = []
    matches = 0
    for path in root_paths:
        for identity, body in _extract_test_identities(path, _git_blob(SNAPSHOT_COMMIT, path)):
            root_identities.append(identity)
            if identity not in base_map:
                raw_gaps.append(identity)
                continue
            matches += 1
            if base_map[identity] != body:
                divergences.append((identity, path))

    semantic_review = sorted(
        identity
        for identity in raw_gaps
        if identity not in RETIRED_DATACLASS_IDENTITIES
    )
    reviewed_divergences = sorted(
        identity
        for identity, path in divergences
        if path in REVIEW_ROOT_PATHS
    )
    return {
        "root_identities": sorted(root_identities),
        "raw_gaps": sorted(raw_gaps),
        "semantic_review": semantic_review,
        "reviewed_divergences": reviewed_divergences,
        "matches": matches,
    }


def _flatten_semantic_entries(
    section: dict[str, list[dict[str, str]]],
    key: str,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for grouped_entries in section.values():
        for item in grouped_entries:
            entries.append(item)
            assert key in item
    return entries


def _current_canonical_nodes() -> set[str]:
    nodes: set[str] = set()
    for path in _tracked_paths("src/tests"):
        if not path.endswith(".py"):
            continue
        for identity, _body in _extract_test_identities(
            path.removeprefix("src/"),
            (ROOT / path).read_text(encoding="utf-8"),
        ):
            nodes.add(identity)
    return nodes


def _normalize_collection_errors(output: str) -> list[str]:
    header_pattern = re.compile(
        r"^_+\s+ERROR collecting (src/tests/.+?[.]py)\s+_+\s*$",
        re.MULTILINE,
    )
    headers = list(header_pattern.finditer(output))
    normalized: list[str] = []
    header_modules: list[str] = []

    for index, header in enumerate(headers):
        module = header.group(1)
        header_modules.append(module)
        block_end = (
            headers[index + 1].start()
            if index + 1 < len(headers)
            else len(output)
        )
        block = output[header.end() : block_end]
        origin = re.search(
            r'^E\s+File "[^\"]*?/(src/[^\"]+[.]py)", line ([0-9]+)$',
            block,
            re.MULTILINE,
        )
        exception = re.search(
            r"^E\s+([A-Za-z_][\w.]+(?:Error|Exception): .+)$",
            block,
            re.MULTILINE,
        )
        if origin is None or exception is None:
            normalized.append(f"{module}|<unparsed origin>|<unparsed exception>")
            continue
        normalized.append(
            f"{module}|{origin.group(1)}:{origin.group(2)}|"
            f"{exception.group(1)}"
        )

    summary_modules = re.findall(
        r"^ERROR (src/tests/.+?[.]py)(?:\s+-.*)?$",
        output,
        re.MULTILINE,
    )
    unmatched_summaries = list(summary_modules)
    for module in header_modules:
        if module in unmatched_summaries:
            unmatched_summaries.remove(module)
        else:
            normalized.append(f"{module}|<missing summary>|<unparsed exception>")
    for module in unmatched_summaries:
        normalized.append(f"{module}|<missing header>|<unparsed exception>")

    reported_count = re.search(
        r"Interrupted: ([0-9]+) errors? during collection",
        output,
    )
    if reported_count is not None and int(reported_count.group(1)) != len(headers):
        normalized.append(
            "<collection>|<summary>|"
            f"reported {reported_count.group(1)} errors for {len(headers)} headers"
        )
    return sorted(normalized)


def _collect_nodes(
    *extra_args: str,
) -> tuple[int, set[str], set[str], list[str], str]:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *extra_args,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    combined_output = "\n".join(
        part for part in (result.stdout, result.stderr) if part
    )
    node_pattern = re.compile(r"^(src/tests|tests)/.+\.py(?:::.+)?$")
    nodes = {
        line.strip()
        for line in combined_output.splitlines()
        if node_pattern.match(line.strip())
    }
    root_nodes = {node for node in nodes if node.startswith("tests/")}
    errors = _normalize_collection_errors(combined_output)
    return result.returncode, nodes, root_nodes, errors, combined_output


def test_root_test_retention_audit_freezes_the_retained_tree() -> None:
    audit = _load_audit()
    retained = audit["retained_paths"]
    all_root = retained["all_tracked"]
    duplicate = retained["duplicate_retained"]
    review = retained["migrate_review_retained"]
    inert = retained["obsolete_inert_retained"]
    tracked_paths = set(_tracked_paths("tests"))

    metadata = dict(audit["metadata"])
    metadata["retention_date"] = str(metadata["retention_date"])
    assert metadata == {
        "name": "root-test-tree-retention",
        "retention_version": 1,
        "retention_date": "2026-08-16",
        "owner_repository": "Artemis_City",
        "status": "active",
        "audited_snapshot": SNAPSHOT_COMMIT,
        "task_base_commit": TASK_BASE_COMMIT,
        "task5_parent_commit": AUDITED_TASK5_PARENT_COMMIT,
        "task5_commit": AUDITED_TASK5_COMMIT,
    }
    assert audit["authority"] == {
        "authorizes_deletion": False,
        "authorizes_move": False,
        "authorizes_rename": False,
        "authorizes_content_rewrite": False,
        "root_test_collection_authority": False,
        "src_test_collection_authority": True,
        "retained_until": "merge_complete_and_reviews_complete",
        "non_authority_statement": (
            "retained root tests are evidence only and receive no collection, "
            "runtime, import, routing, or release authority merely by "
            "remaining tracked"
        ),
    }
    collection = audit["collection_baseline"]
    pinned_errors = collection["pinned_error_multiset"]
    assert collection["allowed_states"] == {
        "clean": {"return_code": 0, "error_multiset": "empty"},
        "pinned_baseline": {"return_code": 2, "error_multiset": "exact"},
    }
    assert collection["affected_modules"] == sorted(
        AFFECTED_COLLECTION_MODULES
    )
    assert pinned_errors["count"] == EXPECTED_COLLECTION_ERROR_COUNT
    assert pinned_errors["line_sha256"] == EXPECTED_COLLECTION_ERROR_SHA
    assert len(pinned_errors["entries"]) == EXPECTED_COLLECTION_ERROR_COUNT
    assert (
        _canonical_line_sha(pinned_errors["entries"])
        == EXPECTED_COLLECTION_ERROR_SHA
    )
    pinned_modules = {
        error.split("|", 1)[0] for error in pinned_errors["entries"]
    }
    assert pinned_modules == AFFECTED_COLLECTION_MODULES
    assert all_root["count"] == EXPECTED_ALL_ROOT_COUNT
    assert all_root["line_sha256"] == EXPECTED_ALL_ROOT_SHA
    assert duplicate["count"] == EXPECTED_DUPLICATE_COUNT
    assert duplicate["line_sha256"] == EXPECTED_DUPLICATE_SHA
    assert review["count"] == EXPECTED_REVIEW_COUNT
    assert review["line_sha256"] == EXPECTED_REVIEW_SHA
    assert inert["count"] == EXPECTED_INERT_COUNT
    assert inert["line_sha256"] == EXPECTED_INERT_SHA

    all_paths = all_root["paths"]
    duplicate_paths = duplicate["paths"]
    review_paths = review["paths"]
    inert_paths = inert["paths"]

    assert _canonical_line_sha(all_paths) == EXPECTED_ALL_ROOT_SHA
    assert _canonical_line_sha(duplicate_paths) == EXPECTED_DUPLICATE_SHA
    assert _canonical_line_sha(review_paths) == EXPECTED_REVIEW_SHA
    assert _canonical_line_sha(inert_paths) == EXPECTED_INERT_SHA
    assert set(all_paths) == set(duplicate_paths) | set(review_paths) | set(inert_paths)
    assert set(duplicate_paths).isdisjoint(review_paths)
    assert set(duplicate_paths).isdisjoint(inert_paths)
    assert set(review_paths).isdisjoint(inert_paths)

    missing = [
        path
        for path in all_paths
        if path not in tracked_paths or not (ROOT / path).exists()
    ]
    assert not missing, f"REVERSE_SYNC_HOLD_VIOLATION retained_root_paths_missing: {missing[:5]}"
    assert all(not (ROOT / path).is_symlink() for path in all_paths)
    assert all(Path(path).parts[0] == "tests" for path in all_paths)
    assert audit["review_signoffs"] == []


def test_root_test_retention_mechanical_baselines_match_the_audited_snapshot() -> None:
    audit = _load_audit()
    mechanical = audit["mechanical_audit"]
    computed = _audited_identity_sets()

    assert len(computed["root_identities"]) == EXPECTED_ROOT_DEFS
    assert computed["matches"] == EXPECTED_MATCHES
    assert len(computed["raw_gaps"]) == EXPECTED_RAW_GAP_COUNT
    assert _canonical_line_sha(computed["raw_gaps"]) == EXPECTED_RAW_GAP_SHA
    assert len(RETIRED_DATACLASS_IDENTITIES) == EXPECTED_RETIRED_COUNT
    assert _canonical_line_sha(sorted(RETIRED_DATACLASS_IDENTITIES)) == EXPECTED_RETIRED_SHA
    assert len(computed["semantic_review"]) == EXPECTED_REVIEW_QUEUE_COUNT
    assert _canonical_line_sha(computed["semantic_review"]) == EXPECTED_REVIEW_QUEUE_SHA
    assert len(computed["reviewed_divergences"]) == EXPECTED_DIVERGENCE_COUNT
    assert _canonical_line_sha(computed["reviewed_divergences"]) == EXPECTED_DIVERGENCE_SHA

    yaml_review = []
    for identities in mechanical["semantic_review_queue"]["identities_by_source"].values():
        yaml_review.extend(identities)
    assert sorted(yaml_review) == computed["semantic_review"]
    assert sorted(mechanical["retired_dataclass_gaps"]["identities"]) == sorted(
        RETIRED_DATACLASS_IDENTITIES
    )
    assert sorted(
        mechanical["same_identity_body_divergences"]["identities"]
    ) == computed["reviewed_divergences"]


def test_root_test_retention_semantic_partition_is_complete_and_targeted() -> None:
    audit = _load_audit()
    semantic = audit["semantic_disposition"]
    computed = _audited_identity_sets()
    current_nodes = _current_canonical_nodes()

    covered = _flatten_semantic_entries(semantic["covered_by_current_contract"], "source_identity")
    retired = _flatten_semantic_entries(semantic["retired_or_superseded"], "source_identity")
    missing = _flatten_semantic_entries(
        semantic["missing_current_contract_intent"],
        "source_identity",
    )
    semantic_identities = sorted(item["source_identity"] for item in covered + retired + missing)

    assert semantic["counts"] == EXPECTED_SEMANTIC_COUNTS
    assert semantic["counts_by_source"] == EXPECTED_SOURCE_COUNTS
    assert semantic_identities == computed["semantic_review"]
    assert len(semantic_identities) == len(set(semantic_identities))

    for entry in covered:
        assert entry["current_test"] in current_nodes
        assert entry["note"]
    for entry in retired:
        assert entry["current_runtime_evidence"]
        assert entry["note"]
    for entry in missing:
        assert entry["target_test"] in current_nodes
        assert entry["note"]
    assert TARGET_TESTS <= current_nodes


def test_root_test_retention_canonical_modules_do_not_depend_on_root_tests() -> None:
    for path in OWNED_CANONICAL_TESTS:
        text = path.read_text(encoding="utf-8")
        assert "from tests" not in text
        assert "import tests" not in text
        assert "tests/" not in text

    staged = {
        line
        for line in _run_git(
            "diff",
            "--cached",
            "--name-only",
            "--",
            "tests",
        ).splitlines()
        if line
    }
    audited_commit_paths = {
        line
        for line in _run_git(
            "diff",
            "--name-only",
            AUDITED_TASK5_PARENT_COMMIT,
            AUDITED_TASK5_COMMIT,
            "--",
            "tests",
        ).splitlines()
        if line
    }
    assert not staged, f"REVERSE_SYNC_HOLD_VIOLATION staged_root_test_changes={sorted(staged)}"
    assert not audited_commit_paths, (
        "REVERSE_SYNC_HOLD_VIOLATION "
        f"committed_root_test_changes={sorted(audited_commit_paths)}"
    )


def test_root_test_retention_pyproject_and_collection_cutover_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]

    assert pytest_options["testpaths"] == ["src/tests"]

    (
        default_rc,
        default_nodes,
        default_root_nodes,
        default_errors,
        default_output,
    ) = _collect_nodes()
    (
        explicit_rc,
        explicit_nodes,
        explicit_root_nodes,
        explicit_errors,
        explicit_output,
    ) = _collect_nodes("src/tests")
    assert default_nodes == explicit_nodes
    assert default_errors == explicit_errors
    pinned_errors = sorted(
        _load_audit()["collection_baseline"]["pinned_error_multiset"]["entries"]
    )
    collections = (
        ("default", default_rc, default_nodes, default_errors, default_output),
        (
            "explicit",
            explicit_rc,
            explicit_nodes,
            explicit_errors,
            explicit_output,
        ),
    )
    for label, return_code, nodes, errors, output in collections:
        if errors:
            assert return_code == 2, f"{label} unexpected rc={return_code}\n{output}"
            assert errors == pinned_errors, (
                f"{label} unexpected collection errors={errors}\n{output}"
            )
        else:
            assert return_code == 0, f"{label} unexpected rc={return_code}\n{output}"
        for module in AFFECTED_COLLECTION_MODULES:
            represented_error = any(
                error.startswith(f"{module}|") for error in errors
            )
            collected_node = any(
                node.startswith(f"{module}::") for node in nodes
            )
            assert represented_error or collected_node, (
                f"{label} silently excluded affected module={module}"
            )
    collection_exclusions = _collection_exclusions()
    default_excluded_nodes = {
        node
        for node in default_nodes
        if node.split("::", 1)[0] in collection_exclusions
    }
    explicit_excluded_nodes = {
        node
        for node in explicit_nodes
        if node.split("::", 1)[0] in collection_exclusions
    }
    assert not default_excluded_nodes, (
        "QUARANTINE_COLLECTION_VIOLATION "
        f"default_collection={sorted(default_excluded_nodes)}"
    )
    assert not explicit_excluded_nodes, (
        "QUARANTINE_COLLECTION_VIOLATION "
        f"explicit_collection={sorted(explicit_excluded_nodes)}"
    )
    configured_ignores = {
        option.removeprefix("--ignore=")
        for option in shlex.split(pytest_options["addopts"])
        if option.startswith("--ignore=")
    }
    canonical_exclusions = {
        path for path in collection_exclusions if path.startswith("src/tests/")
    }
    assert canonical_exclusions <= configured_ignores
    assert not default_root_nodes, (
        "REVERSE_SYNC_HOLD_VIOLATION "
        f"default_collection_includes_root_tests={sorted(default_root_nodes)}"
    )
    assert not explicit_root_nodes, (
        "REVERSE_SYNC_HOLD_VIOLATION "
        f"explicit_collection_includes_root_tests={sorted(explicit_root_nodes)}"
    )
