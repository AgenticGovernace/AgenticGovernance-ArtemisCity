"""Fail-closed contracts for the active Python release hold."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tarfile
import zipfile
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_HOLD_PATH = ROOT / "docs" / "audits" / "2026-08-16-python-release-hold.yaml"
WHEEL_CANDIDATE_PATH = (
    ROOT / "docs" / "audits" / "2026-08-16-python-wheel-candidate.v1.txt"
)
SDIST_CANDIDATE_PATH = (
    ROOT / "docs" / "audits" / "2026-08-16-python-sdist-candidate.v1.txt"
)
WHEEL_ALLOWLIST = ROOT / "config" / "release" / "python-wheel-files.v1.txt"
SDIST_ALLOWLIST = ROOT / "config" / "release" / "python-sdist-files.v1.txt"
RELEASE_HOLD_REASON = "RELEASE_HOLD_ACTIVE: Python package release is blocked."
EXPECTED_OBSERVED_COMMIT = "6462c4c2b51e66d6c51728ee6c9decb31e2ef651"
EXPECTED_CANDIDATE_COUNT = 106
EXPECTED_CANDIDATE_LINE_SHA256 = (
    "d500a3eee4f1d9902c08c31aa347f953ddfedcaebaf48a8a7f70e65bb43948bb"
)
EXPECTED_CANDIDATE_CONTENT_SHA256 = (
    "3044ce0c6ee21017f6f33b183eed2ed4d3e0e66001ff0fa785aad5a0a2da5d68"
)
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "a04e80d3286d1e91d7784b1788fb8c2b460c84ce693956dfee544066508dfdd5"
)
EMPTY_LINE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
FACADE_LINE_SHA256 = "936bea53d1e9b571a6ba963af54e1f8aaf0ca01dc75d209aea443d3210b0470a"
EXPECTED_BROAD_ARTIFACTS = {
    "wheel": {
        "archive_sha256": (
            "6f5f46fc626705080bc476ff7ae41dc1225d52f1307501d8498e81da5f8661f7"
        ),
        "member_count": 425,
        "normalized_member_line_sha256": (
            "4f18f09033082149f8955aa257a1beea15e4dff2643fe4575a3173a87268c0ef"
        ),
        "held": (
            102,
            "0cef4ad99504c8af45cc872678ade25b6a2b3d911bf95d05651407994a552474",
        ),
        "retained_root": (0, EMPTY_LINE_SHA256),
        "quarantine": (
            37,
            "9741fc471249a157df929f273c455a7d602915dd31387acc2127f612322157fb",
        ),
    },
    "sdist": {
        "archive_sha256": (
            "0f0c112fa9662436ea7a8889fb7b5e7a2f0afd6f6feca7807a843de4d92c6133"
        ),
        "member_count": 793,
        "normalized_member_line_sha256": (
            "8a1d1ecf3f0d13657a41f76b1ce30c6e794236662683eee0e199260302244bb5"
        ),
        "held": (
            217,
            "2f07edf48b8a82bd10a35826c3df009d4d60a3f54593db4a424d309d644b1f3b",
        ),
        "retained_root": (
            64,
            "426986bc9b60dbd4266f1d09cf76ee8656ad0b6dc598d2a812ffb5515ef80f60",
        ),
        "quarantine": (
            45,
            "b45297b6c2de2bf734e7cb4faee9196ab3dd0e62f5a12048502e3b26af243873",
        ),
    },
}
EXPECTED_BLOCKER_CODES = {
    "auth_receipt_schema_unpublishable",
    "authstructure_conformance_missing",
    "compatibility_facade_release_authority_undecided",
    "console_entry_point_undecided",
    "credential_value_filter_incomplete",
    "fresh_user_release_authorization_pending",
    "full_tests_pending",
    "installed_wheel_imports_unverified",
    "instruction_loader_import_broken",
    "merge_pending",
    "minimal_dependencies_unlocked",
    "receipt_projection_mutable",
    "reproducible_artifacts_unverified",
    "review_completion_pending",
    "routing_envelope_schema_unpublishable",
    "runtime_paths_not_operator_writable",
    "tracked_release_allowlists_absent",
}
EXPECTED_LIFT_CONDITIONS = {
    "auth_schemas_publishable",
    "authstructure_conformance_green",
    "compatibility_facade_decided",
    "console_entry_point_decided",
    "fresh_user_release_authorization",
    "full_tests_green",
    "installed_wheel_imports_green",
    "instruction_loader_import_green",
    "merge_complete",
    "minimal_dependencies_locked",
    "receipt_projection_immutable",
    "receipt_values_safe",
    "release_review_complete",
    "reproducible_artifacts_green",
    "runtime_paths_operator_writable",
    "tracked_allowlists_reviewed",
}
EXPECTED_BLOCKER_LIFT_CONDITIONS = {
    "auth_receipt_schema_unpublishable": "auth_schemas_publishable",
    "authstructure_conformance_missing": "authstructure_conformance_green",
    "compatibility_facade_release_authority_undecided": (
        "compatibility_facade_decided"
    ),
    "console_entry_point_undecided": "console_entry_point_decided",
    "credential_value_filter_incomplete": "receipt_values_safe",
    "fresh_user_release_authorization_pending": "fresh_user_release_authorization",
    "full_tests_pending": "full_tests_green",
    "installed_wheel_imports_unverified": "installed_wheel_imports_green",
    "instruction_loader_import_broken": "instruction_loader_import_green",
    "merge_pending": "merge_complete",
    "minimal_dependencies_unlocked": "minimal_dependencies_locked",
    "receipt_projection_mutable": "receipt_projection_immutable",
    "reproducible_artifacts_unverified": "reproducible_artifacts_green",
    "review_completion_pending": "release_review_complete",
    "routing_envelope_schema_unpublishable": "auth_schemas_publishable",
    "runtime_paths_not_operator_writable": "runtime_paths_operator_writable",
    "tracked_release_allowlists_absent": "tracked_allowlists_reviewed",
}
BLOCKER_EVIDENCE_KEYS = {
    "auth_receipt_schema_unpublishable": {
        "probe",
        "return_code",
        "error_type",
        "unsupported_type",
    },
    "authstructure_conformance_missing": {
        "verifier_port",
        "external_conformance_result",
    },
    "compatibility_facade_release_authority_undecided": {
        "path",
        "candidate_quarantine_intersection",
    },
    "console_entry_point_undecided": {"pyproject_project_scripts_present"},
    "credential_value_filter_incomplete": {
        "synthetic_bearer_under_noncredential_key_accepted"
    },
    "fresh_user_release_authorization_pending": {"authorization_records"},
    "full_tests_pending": {"full_suite_result"},
    "installed_wheel_imports_unverified": {"installed_candidate_wheel_result"},
    "instruction_loader_import_broken": {
        "probe",
        "return_code",
        "error_type",
        "source_line",
    },
    "merge_pending": {"merge_signoffs"},
    "minimal_dependencies_unlocked": {
        "declared_runtime_dependency_count",
        "reviewed_minimal_dependency_lock",
    },
    "receipt_projection_mutable": {"frozen_json_dict_values_reassignment_succeeded"},
    "reproducible_artifacts_unverified": {"exact_candidate_rebuilds_compared"},
    "review_completion_pending": {"human_review_signoffs"},
    "routing_envelope_schema_unpublishable": {
        "probe",
        "return_code",
        "error_type",
        "unsupported_type",
    },
    "runtime_paths_not_operator_writable": {
        "default_root_expression",
        "installed_site_packages_write_risk",
    },
    "tracked_release_allowlists_absent": {
        "wheel_allowlist_present",
        "sdist_allowlist_present",
    },
}
FORBIDDEN_PARTS = {
    "__pycache__",
    "node_modules",
    "memory_store",
    "obsidian_vault",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".wav",
    ".zip",
    ".ipynb",
    ".pyc",
}
QUARANTINE_EXTRA_PATHS = {
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
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml(path: Path) -> dict[str, object]:
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    assert isinstance(document, dict)
    return document


def _exact_mapping(
    value: object,
    expected_keys: set[str],
    context: str,
) -> dict[str, object]:
    assert isinstance(value, dict), (
        f"RELEASE_HOLD_SCHEMA: {context} must be a mapping, "
        f"found {type(value).__name__}."
    )
    actual_keys = set(value)
    assert actual_keys == expected_keys, (
        f"RELEASE_HOLD_SCHEMA: {context} keys differ; "
        f"missing={sorted(expected_keys - actual_keys)}, "
        f"extra={sorted(actual_keys - expected_keys)}."
    )
    return value


def _mapping_list(value: object, context: str) -> list[object]:
    assert isinstance(value, list), (
        f"RELEASE_HOLD_SCHEMA: {context} must be a list, "
        f"found {type(value).__name__}."
    )
    return value


def _assert_release_hold_schema(hold: dict[str, object]) -> None:
    document = _exact_mapping(
        hold,
        {
            "api_version",
            "kind",
            "metadata",
            "observation",
            "approved_release_allowlists",
            "broad_clean_commit_artifacts",
            "candidates",
            "blockers",
            "permissions",
            "lift_conditions",
            "signoffs",
        },
        "document",
    )
    _exact_mapping(
        document["metadata"],
        {"name", "hold_version", "hold_date", "owner_repository", "status"},
        "metadata",
    )
    observation = _exact_mapping(
        document["observation"],
        {
            "commit",
            "branch",
            "commit_time",
            "evidence_source",
            "dirty_at_evidence_refresh",
            "dirty_path_count_at_evidence_refresh",
            "dirty_status_encoding",
            "dirty_status_line_sha256",
            "dirty_observation_is_release_evidence",
            "tool_versions",
        },
        "observation",
    )
    _exact_mapping(
        observation["tool_versions"],
        {"python", "git", "make", "build", "hatchling", "pytest", "pyyaml"},
        "observation.tool_versions",
    )

    approved = _exact_mapping(
        document["approved_release_allowlists"],
        {"wheel", "sdist"},
        "approved_release_allowlists",
    )
    for label in ("wheel", "sdist"):
        _exact_mapping(
            approved[label],
            {
                "path",
                "present_at_observed_commit",
                "present_in_worktree",
                "authorized",
            },
            f"approved_release_allowlists.{label}",
        )

    broad = _exact_mapping(
        document["broad_clean_commit_artifacts"],
        {"source", "build_command", "normalized_member_encoding", "wheel", "sdist"},
        "broad_clean_commit_artifacts",
    )
    _exact_mapping(
        broad["source"],
        {
            "commit",
            "tree",
            "git_archive_sha256",
            "pyproject_blob_oid",
            "pyproject_sha256",
        },
        "broad_clean_commit_artifacts.source",
    )
    for label in ("wheel", "sdist"):
        artifact = _exact_mapping(
            broad[label],
            {
                "artifact_name",
                "build_return_code",
                "archive_sha256",
                "member_count",
                "normalized_member_line_sha256",
                "protected_intersections",
            },
            f"broad_clean_commit_artifacts.{label}",
        )
        intersections = _exact_mapping(
            artifact["protected_intersections"],
            {"held", "retained_root", "quarantine"},
            f"broad_clean_commit_artifacts.{label}.protected_intersections",
        )
        for partition in ("held", "retained_root", "quarantine"):
            _exact_mapping(
                intersections[partition],
                {"count", "line_sha256"},
                f"broad_clean_commit_artifacts.{label}.{partition}",
            )

    candidates = _exact_mapping(
        document["candidates"],
        {"wheel", "sdist"},
        "candidates",
    )
    for label in ("wheel", "sdist"):
        candidate = _exact_mapping(
            candidates[label],
            {
                "path",
                "role",
                "approved",
                "count",
                "sorted_path_encoding",
                "sorted_path_sha256",
                "content_digest_encoding",
                "path_nul_blob_nul_sha256",
                "oid_manifest_encoding",
                "path_tab_blob_oid_manifest_sha256",
                "protected_intersections",
                "experimental_artifact",
            },
            f"candidates.{label}",
        )
        intersections = _exact_mapping(
            candidate["protected_intersections"],
            {"held", "retained_root", "quarantine"},
            f"candidates.{label}.protected_intersections",
        )
        for partition in ("held", "retained_root", "quarantine"):
            _exact_mapping(
                intersections[partition],
                {"count", "line_sha256", "paths"},
                f"candidates.{label}.{partition}",
            )
        _exact_mapping(
            candidate["experimental_artifact"],
            {
                "status",
                "reason_code",
                "normalized_member_count",
                "normalized_member_line_sha256",
            },
            f"candidates.{label}.experimental_artifact",
        )

    blockers = _exact_mapping(
        document["blockers"],
        {"recognized_reason_codes", "active"},
        "blockers",
    )
    _mapping_list(
        blockers["recognized_reason_codes"], "blockers.recognized_reason_codes"
    )
    active_blockers = _mapping_list(blockers["active"], "blockers.active")
    for index, blocker_value in enumerate(active_blockers):
        blocker = _exact_mapping(
            blocker_value,
            {"reason_code", "status", "lift_condition", "evidence"},
            f"blockers.active[{index}]",
        )
        reason_code = blocker["reason_code"]
        assert isinstance(reason_code, str) and reason_code in BLOCKER_EVIDENCE_KEYS, (
            f"RELEASE_HOLD_SCHEMA: blockers.active[{index}] has unrecognized "
            f"reason_code {reason_code!r}."
        )
        _exact_mapping(
            blocker["evidence"],
            BLOCKER_EVIDENCE_KEYS[reason_code],
            f"blockers.active[{index}].evidence",
        )

    _exact_mapping(
        document["permissions"],
        {
            "authorizes_allowlist_creation",
            "authorizes_build",
            "authorizes_configuration_change",
            "authorizes_content_rewrite",
            "authorizes_deletion",
            "authorizes_move",
            "authorizes_publish",
            "authorizes_release",
            "authorizes_rename",
            "authorizes_restore",
            "candidate_grants_release_authority",
        },
        "permissions",
    )
    lift_conditions = _mapping_list(document["lift_conditions"], "lift_conditions")
    for index, condition in enumerate(lift_conditions):
        _exact_mapping(
            condition,
            {"key", "satisfied"},
            f"lift_conditions[{index}]",
        )
    _exact_mapping(
        document["signoffs"],
        {"human_review", "merge", "user_release_authorization"},
        "signoffs",
    )


def _load_release_hold() -> dict[str, object]:
    hold = _load_yaml(RELEASE_HOLD_PATH)
    _assert_release_hold_schema(hold)
    return hold


def test_release_hold_contract_yaml_loader_rejects_duplicate_keys(
    tmp_path: Path,
) -> None:
    duplicate_yaml = tmp_path / "duplicate.yaml"
    duplicate_yaml.write_text(
        "permissions:\n" "  authorizes_build: false\n" "  authorizes_build: true\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        _load_yaml(duplicate_yaml)


def _mapping_paths(
    value: object,
    path: tuple[str | int, ...] = (),
) -> list[tuple[str | int, ...]]:
    paths: list[tuple[str | int, ...]] = []
    if isinstance(value, dict):
        paths.append(path)
        for key, child in value.items():
            paths.extend(_mapping_paths(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_mapping_paths(child, (*path, index)))
    return paths


def test_release_hold_contract_schema_rejects_extra_fields_in_every_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = RELEASE_HOLD_PATH
    original = _load_yaml(source_path)
    mapping_paths = _mapping_paths(original)

    assert mapping_paths
    for mapping_path in mapping_paths:
        document = _load_yaml(source_path)
        target: object = document
        for part in mapping_path:
            target = target[part]  # type: ignore[index]
        assert isinstance(target, dict)
        target["unexpected_review_field"] = True

        mutated_path = tmp_path / "release-hold-with-extra-field.yaml"
        mutated_path.write_text(
            yaml.safe_dump(document, sort_keys=False),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys.modules[__name__],
            "RELEASE_HOLD_PATH",
            mutated_path,
        )
        with pytest.raises(AssertionError, match="RELEASE_HOLD_SCHEMA"):
            _load_release_hold()


def _git_result(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )


@cache
def _git_blob(commit: str, path: str) -> bytes:
    result = _git_result("show", f"{commit}:{path}")
    assert result.returncode == 0, (
        "RELEASE_HOLD_CANDIDATE_MISSING: "
        f"{path} is absent from observed commit {commit}."
    )
    return result.stdout


@cache
def _git_blob_oid(commit: str, path: str) -> str:
    result = _git_result("rev-parse", f"{commit}:{path}")
    assert result.returncode == 0, result.stderr.decode("utf-8")
    return result.stdout.decode("utf-8").strip()


@cache
def _tracked_paths_at(commit: str) -> set[str]:
    result = _git_result("ls-tree", "-r", "--name-only", commit)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    return set(result.stdout.decode("utf-8").splitlines())


def _line_sha256(items: list[str]) -> str:
    payload = "".join(f"{item}\n" for item in items).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_candidate(path: Path) -> list[str]:
    payload = path.read_bytes()
    assert payload.endswith(b"\n")
    assert b"\r" not in payload
    items = payload.decode("utf-8").splitlines()
    assert items == sorted(items)
    assert len(items) == len(set(items))
    assert all(
        item and not any(token in item for token in ("*", "?", "[")) for item in items
    )
    return items


def _candidate_digests(commit: str, paths: list[str]) -> dict[str, str]:
    content_digest = hashlib.sha256()
    manifest_lines: list[str] = []
    for path in paths:
        content_digest.update(path.encode("utf-8"))
        content_digest.update(b"\0")
        content_digest.update(_git_blob(commit, path))
        content_digest.update(b"\0")
        manifest_lines.append(f"{path}\t{_git_blob_oid(commit, path)}\n")
    return {
        "sorted_path_sha256": _line_sha256(paths),
        "path_nul_blob_nul_sha256": content_digest.hexdigest(),
        "path_tab_blob_oid_manifest_sha256": hashlib.sha256(
            "".join(manifest_lines).encode("utf-8")
        ).hexdigest(),
    }


def _protected_paths(commit: str) -> dict[str, set[str]]:
    manifest = yaml.safe_load(
        _git_blob(
            commit,
            "docs/audits/2026-08-16-reverse-sync-72cf776-path-manifest.yaml",
        )
    )
    held = {
        entry["path"]
        for entry in manifest["paths"]
        if entry["classification"] == "REMOVE_REVERSE_SYNC"
        and entry["source_status"] == "A"
    }
    retention = yaml.safe_load(
        _git_blob(
            commit,
            "docs/audits/2026-08-16-root-test-tree-retention.yaml",
        )
    )
    retained_root = set(retention["retained_paths"]["all_tracked"]["paths"])
    quarantine = {
        path for path in _tracked_paths_at(commit) if path.startswith("src/Kernel/")
    }
    quarantine.update(QUARANTINE_EXTRA_PATHS)
    return {
        "held": held,
        "retained_root": retained_root,
        "quarantine": quarantine,
    }


def _assert_intersection_record(
    record: dict[str, object], actual_paths: list[str]
) -> None:
    assert record["count"] == len(actual_paths)
    assert record["line_sha256"] == _line_sha256(actual_paths)
    assert record["paths"] == actual_paths


def test_release_hold_contract_is_strict_active_and_non_authorizing() -> None:
    hold = _load_release_hold()

    assert set(hold) == {
        "api_version",
        "kind",
        "metadata",
        "observation",
        "approved_release_allowlists",
        "broad_clean_commit_artifacts",
        "candidates",
        "blockers",
        "permissions",
        "lift_conditions",
        "signoffs",
    }
    assert hold["api_version"] == "artemis.quantumharmony.dev/v1"
    assert hold["kind"] == "PythonReleaseHold"
    assert hold["metadata"] == {
        "name": "python-release-hold",
        "hold_version": 1,
        "hold_date": "2026-08-16",
        "owner_repository": "Artemis_City",
        "status": "active",
    }
    assert hold["observation"]["commit"] == EXPECTED_OBSERVED_COMMIT
    assert hold["observation"]["branch"] == "feature/routing-kernel-consolidation"
    assert hold["observation"]["evidence_source"] == "git archive HEAD"

    permissions = hold["permissions"]
    assert set(permissions) == {
        "authorizes_allowlist_creation",
        "authorizes_build",
        "authorizes_configuration_change",
        "authorizes_content_rewrite",
        "authorizes_deletion",
        "authorizes_move",
        "authorizes_publish",
        "authorizes_release",
        "authorizes_rename",
        "authorizes_restore",
        "candidate_grants_release_authority",
    }
    assert permissions and all(value is False for value in permissions.values())
    assert hold["signoffs"] == {
        "human_review": [],
        "merge": [],
        "user_release_authorization": [],
    }

    blockers = hold["blockers"]
    active_codes = [entry["reason_code"] for entry in blockers["active"]]
    assert blockers["recognized_reason_codes"] == sorted(EXPECTED_BLOCKER_CODES)
    assert set(active_codes) == EXPECTED_BLOCKER_CODES
    assert len(active_codes) == len(set(active_codes))
    assert all(entry["status"] == "open" for entry in blockers["active"])

    lift_conditions = hold["lift_conditions"]
    assert {entry["key"] for entry in lift_conditions} == EXPECTED_LIFT_CONDITIONS
    assert all(entry["satisfied"] is False for entry in lift_conditions)


def test_release_hold_contract_maps_every_blocker_to_exact_lift_condition() -> None:
    hold = _load_release_hold()
    conditions = {entry["key"] for entry in hold["lift_conditions"]}
    blocker_mapping = {
        entry["reason_code"]: entry.get("lift_condition")
        for entry in hold["blockers"]["active"]
    }

    assert blocker_mapping == EXPECTED_BLOCKER_LIFT_CONDITIONS
    assert set(blocker_mapping.values()) <= conditions
    assert blocker_mapping["instruction_loader_import_broken"] == (
        "instruction_loader_import_green"
    )


def test_release_hold_contract_keeps_approved_allowlists_absent() -> None:
    hold = _load_release_hold()
    approved = hold["approved_release_allowlists"]
    expected = {
        "wheel": WHEEL_ALLOWLIST.relative_to(ROOT).as_posix(),
        "sdist": SDIST_ALLOWLIST.relative_to(ROOT).as_posix(),
    }

    for label, path in expected.items():
        record = approved[label]
        assert record == {
            "path": path,
            "present_at_observed_commit": False,
            "present_in_worktree": False,
            "authorized": False,
        }
        result = _git_result("cat-file", "-e", f"{EXPECTED_OBSERVED_COMMIT}:{path}")
        assert result.returncode != 0
        assert not (ROOT / path).exists()


def test_release_hold_contract_pins_clean_commit_artifact_evidence() -> None:
    hold = _load_release_hold()
    observation = hold["observation"]
    source = hold["broad_clean_commit_artifacts"]["source"]
    archive = _git_result("archive", "--format=tar", EXPECTED_OBSERVED_COMMIT)

    assert archive.returncode == 0, archive.stderr.decode("utf-8")
    assert source == {
        "commit": EXPECTED_OBSERVED_COMMIT,
        "tree": "354d4369a33cffeb737292128fc3375a94c19f15",
        "git_archive_sha256": (
            "1e72ea1b3331bb43c5f86aeeaae9a33e77819cbb115622151ea03d208ea2515a"
        ),
        "pyproject_blob_oid": "d2cc0242eb8711e507144310d5bf022dfa007262",
        "pyproject_sha256": (
            "8dcf796aee1c1d8c30d1eff0704421b4606c3c2f59429a5f97a860e49eaf6fc1"
        ),
    }
    assert hashlib.sha256(archive.stdout).hexdigest() == source["git_archive_sha256"]
    assert (
        hashlib.sha256(
            _git_blob(EXPECTED_OBSERVED_COMMIT, "pyproject.toml")
        ).hexdigest()
        == source["pyproject_sha256"]
    )
    assert observation["dirty_at_evidence_refresh"] is True
    assert observation["dirty_path_count_at_evidence_refresh"] == 78
    assert observation["dirty_status_line_sha256"] == (
        "8f40b6b69f35d218c76537286dfe400e5468c12a26e4784b5e573bd08303cf0e"
    )

    artifacts = hold["broad_clean_commit_artifacts"]
    for label, expected in EXPECTED_BROAD_ARTIFACTS.items():
        record = artifacts[label]
        assert record["build_return_code"] == 0
        assert record["archive_sha256"] == expected["archive_sha256"]
        assert record["member_count"] == expected["member_count"]
        assert (
            record["normalized_member_line_sha256"]
            == expected["normalized_member_line_sha256"]
        )
        for partition in ("held", "retained_root", "quarantine"):
            intersection = record["protected_intersections"][partition]
            expected_count, expected_sha = expected[partition]
            assert intersection == {
                "count": expected_count,
                "line_sha256": expected_sha,
            }


def test_release_hold_contract_candidates_match_observed_source_blobs() -> None:
    hold = _load_release_hold()
    protected = _protected_paths(EXPECTED_OBSERVED_COMMIT)
    tracked = _tracked_paths_at(EXPECTED_OBSERVED_COMMIT)
    candidate_paths = {
        "wheel": WHEEL_CANDIDATE_PATH,
        "sdist": SDIST_CANDIDATE_PATH,
    }
    observed_candidates: dict[str, list[str]] = {}

    assert len(protected["held"]) == 217
    assert len(protected["retained_root"]) == 64
    assert len(protected["quarantine"]) == 45
    assert protected["held"] <= tracked
    assert protected["retained_root"] <= tracked
    assert protected["quarantine"] <= tracked

    for label, path in candidate_paths.items():
        paths = _read_candidate(path)
        observed_candidates[label] = paths
        record = hold["candidates"][label]
        assert record["path"] == path.relative_to(ROOT).as_posix()
        assert record["role"] == "evidence_only"
        assert record["approved"] is False
        assert record["count"] == EXPECTED_CANDIDATE_COUNT
        assert set(paths) <= tracked
        expected_digests = {
            "sorted_path_sha256": EXPECTED_CANDIDATE_LINE_SHA256,
            "path_nul_blob_nul_sha256": EXPECTED_CANDIDATE_CONTENT_SHA256,
            "path_tab_blob_oid_manifest_sha256": (EXPECTED_CANDIDATE_MANIFEST_SHA256),
        }
        assert _candidate_digests(EXPECTED_OBSERVED_COMMIT, paths) == expected_digests
        assert {
            key: record[key]
            for key in (
                "sorted_path_sha256",
                "path_nul_blob_nul_sha256",
                "path_tab_blob_oid_manifest_sha256",
            )
        } == expected_digests

        path_set = set(paths)
        intersections = record["protected_intersections"]
        for partition, protected_paths in protected.items():
            actual = sorted(path_set & protected_paths)
            _assert_intersection_record(intersections[partition], actual)
        assert intersections["held"]["count"] == 0
        assert intersections["retained_root"]["count"] == 0
        assert intersections["quarantine"]["paths"] == ["src/Kernel/__init__.py"]
        assert record["experimental_artifact"] == {
            "status": "not_attempted",
            "reason_code": "active_hold_configuration_unchanged",
            "normalized_member_count": None,
            "normalized_member_line_sha256": None,
        }

    assert observed_candidates["wheel"] == observed_candidates["sdist"]


def test_allowlist_comparator_accepts_normalized_wheel_dist_info(
    tmp_path: Path,
) -> None:
    allowlist = tmp_path / "wheel-allowlist.txt"
    allowlist.write_text(
        "app/__init__.py\n"
        "{dist_info}/METADATA\n"
        "{dist_info}/WHEEL\n"
        "{dist_info}/RECORD\n",
        encoding="utf-8",
    )

    members = [
        "app/__init__.py",
        "artemis_city-1.0.0.dist-info/METADATA",
        "artemis_city-1.0.0.dist-info/WHEEL",
        "artemis_city-1.0.0.dist-info/RECORD",
    ]

    _assert_members_match_allowlist(
        member_names=members,
        allowlist_path=allowlist,
        artifact_label="wheel",
        normalize_wheel_dist_info=True,
    )


def test_allowlist_comparator_rejects_duplicate_raw_wheel_members(
    tmp_path: Path,
) -> None:
    allowlist = tmp_path / "wheel-allowlist.txt"
    allowlist.write_text(
        "app/__init__.py\n"
        "{dist_info}/METADATA\n"
        "{dist_info}/WHEEL\n"
        "{dist_info}/RECORD\n",
        encoding="utf-8",
    )
    members = [
        "app/__init__.py",
        "app/__init__.py",
        "artemis_city-1.0.0.dist-info/METADATA",
        "artemis_city-1.0.0.dist-info/WHEEL",
        "artemis_city-1.0.0.dist-info/RECORD",
    ]

    with pytest.raises(AssertionError, match="RELEASE_ARTIFACT_DUPLICATE_MEMBER"):
        _assert_members_match_allowlist(
            member_names=members,
            allowlist_path=allowlist,
            artifact_label="wheel",
            normalize_wheel_dist_info=True,
        )


def test_allowlist_comparator_rejects_shadow_wheel_dist_info_root(
    tmp_path: Path,
) -> None:
    allowlist = tmp_path / "wheel-allowlist.txt"
    allowlist.write_text(
        "app/__init__.py\n"
        "{dist_info}/METADATA\n"
        "{dist_info}/WHEEL\n"
        "{dist_info}/RECORD\n",
        encoding="utf-8",
    )
    members = [
        "app/__init__.py",
        "artemis_city-1.0.0.dist-info/METADATA",
        "artemis_city-1.0.0.dist-info/WHEEL",
        "artemis_city-1.0.0.dist-info/RECORD",
        "shadow-0.dist-info/METADATA",
    ]

    with pytest.raises(AssertionError, match="RELEASE_WHEEL_DIST_INFO_ROOT_COUNT"):
        _assert_members_match_allowlist(
            member_names=members,
            allowlist_path=allowlist,
            artifact_label="wheel",
            normalize_wheel_dist_info=True,
        )


def test_allowlist_comparator_rejects_placeholder_allowlist(tmp_path: Path) -> None:
    allowlist = tmp_path / "wheel-allowlist.txt"
    allowlist.write_text("", encoding="utf-8")

    with pytest.raises(AssertionError, match="RELEASE_ALLOWLIST_MISMATCH"):
        _assert_members_match_allowlist(
            member_names=[
                "app/__init__.py",
                "artemis_city-1.0.0.dist-info/METADATA",
            ],
            allowlist_path=allowlist,
            artifact_label="wheel",
            normalize_wheel_dist_info=True,
        )


def test_forbidden_member_rules_remain_closed() -> None:
    violations = _artifact_scope_violations(
        [
            "src/Kernel/router.py",
            "src/tests/test_router.py",
            "src/cache.pyc",
            "src/model copy.py",
            "src/state.db",
            "dist/prior.whl",
        ]
    )

    assert violations == [
        "copy-suffix:src/model copy.py",
        "forbidden-suffix:src/cache.pyc",
        "forbidden-suffix:src/state.db",
        "prior-dist:dist/prior.whl",
        "src-kernel:src/Kernel/router.py",
        "tests-tree:src/tests/test_router.py",
    ]


@pytest.fixture(scope="module")
def built_release_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Path]:
    if _load_release_hold()["metadata"]["status"] == "active":
        pytest.skip(RELEASE_HOLD_REASON)

    outdir = tmp_path_factory.mktemp("release-artifacts")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--no-isolation",
            "--outdir",
            str(outdir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {
        "wheel": next(outdir.glob("*.whl")),
        "sdist": next(outdir.glob("*.tar.gz")),
    }


def _artifact_members(artifact_path: Path) -> list[str]:
    if artifact_path.suffix == ".whl":
        with zipfile.ZipFile(artifact_path) as archive:
            return archive.namelist()

    members: list[str] = []
    with tarfile.open(artifact_path) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = PurePosixPath(member.name)
            normalized = PurePosixPath(*path.parts[1:]) if len(path.parts) > 1 else path
            members.append(normalized.as_posix())
    return members


def _normalize_allowlist_member(
    member_name: str, *, normalize_wheel_dist_info: bool
) -> str:
    path = PurePosixPath(member_name)
    if (
        normalize_wheel_dist_info
        and path.parts
        and path.parts[0].endswith(".dist-info")
    ):
        return PurePosixPath("{dist_info}", *path.parts[1:]).as_posix()
    return path.as_posix()


def _read_allowlist(
    allowlist_path: Path, *, normalize_wheel_dist_info: bool
) -> list[str]:
    return [
        _normalize_allowlist_member(
            line.strip(),
            normalize_wheel_dist_info=normalize_wheel_dist_info,
        )
        for line in allowlist_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _artifact_scope_violations(member_names: list[str]) -> list[str]:
    violations: list[str] = []
    casefolded: dict[str, list[str]] = defaultdict(list)

    for member_name in member_names:
        path = PurePosixPath(member_name)
        casefolded[member_name.casefold()].append(member_name)
        if any(part in FORBIDDEN_PARTS for part in path.parts):
            violations.append(f"forbidden-part:{member_name}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            violations.append(f"forbidden-suffix:{member_name}")
        if "tests" in path.parts:
            violations.append(f"tests-tree:{member_name}")
        if (
            path.parts[:2] == ("src", "Kernel")
            and member_name != "src/Kernel/__init__.py"
        ):
            violations.append(f"src-kernel:{member_name}")
        if path.parts and path.parts[0] == "dist":
            violations.append(f"prior-dist:{member_name}")
        if " 2." in path.name or " copy." in path.name.casefold():
            violations.append(f"copy-suffix:{member_name}")

    for duplicate_group in casefolded.values():
        if len(duplicate_group) > 1:
            violations.append(f"casefold-collision:{sorted(duplicate_group)}")
    return sorted(set(violations))


def _assert_allowlist_exists(path: Path, artifact_label: str) -> None:
    assert path.is_file(), (
        "RELEASE_ALLOWLIST_MISSING: "
        f"{artifact_label} allowlist {_display_path(path)} must exist after the "
        "release hold is lifted."
    )


def _display_path(path: Path) -> str:
    if path.is_relative_to(ROOT):
        return path.relative_to(ROOT).as_posix()
    return path.as_posix()


def _assert_members_match_allowlist(
    *,
    member_names: list[str],
    allowlist_path: Path,
    artifact_label: str,
    normalize_wheel_dist_info: bool,
) -> None:
    _assert_allowlist_exists(allowlist_path, artifact_label)
    duplicate_members = sorted(
        member for member, count in Counter(member_names).items() if count > 1
    )
    assert not duplicate_members, (
        "RELEASE_ARTIFACT_DUPLICATE_MEMBER: "
        f"{artifact_label} repeats raw members {duplicate_members[:20]}."
    )

    if normalize_wheel_dist_info:
        dist_info_roots = sorted(
            {
                path.parts[0]
                for member_name in member_names
                if (path := PurePosixPath(member_name)).parts
                and path.parts[0].endswith(".dist-info")
            }
        )
        assert len(dist_info_roots) == 1, (
            "RELEASE_WHEEL_DIST_INFO_ROOT_COUNT: "
            f"expected one raw .dist-info root, found {dist_info_roots}."
        )

    normalized_members = sorted(
        _normalize_allowlist_member(
            member_name,
            normalize_wheel_dist_info=normalize_wheel_dist_info,
        )
        for member_name in member_names
    )
    allowlist_members = sorted(
        _read_allowlist(
            allowlist_path,
            normalize_wheel_dist_info=normalize_wheel_dist_info,
        )
    )
    missing = sorted(
        (Counter(allowlist_members) - Counter(normalized_members)).elements()
    )
    unexpected = sorted(
        (Counter(normalized_members) - Counter(allowlist_members)).elements()
    )
    assert normalized_members == allowlist_members, (
        "RELEASE_ALLOWLIST_MISMATCH: "
        f"{artifact_label} differs from {_display_path(allowlist_path)}; "
        f"missing={missing[:20]}, unexpected={unexpected[:20]}."
    )


def test_release_hold_contract_wheel_rejects_forbidden_members(
    built_release_artifacts: dict[str, Path],
) -> None:
    violations = _artifact_scope_violations(
        _artifact_members(built_release_artifacts["wheel"])
    )
    assert not violations, violations[:40]


def test_release_hold_contract_sdist_rejects_forbidden_members(
    built_release_artifacts: dict[str, Path],
) -> None:
    violations = _artifact_scope_violations(
        _artifact_members(built_release_artifacts["sdist"])
    )
    assert not violations, violations[:40]


def test_release_hold_contract_wheel_matches_lifted_allowlist(
    built_release_artifacts: dict[str, Path],
) -> None:
    _assert_members_match_allowlist(
        member_names=_artifact_members(built_release_artifacts["wheel"]),
        allowlist_path=WHEEL_ALLOWLIST,
        artifact_label="wheel",
        normalize_wheel_dist_info=True,
    )


def test_release_hold_contract_sdist_matches_lifted_allowlist(
    built_release_artifacts: dict[str, Path],
) -> None:
    _assert_members_match_allowlist(
        member_names=_artifact_members(built_release_artifacts["sdist"]),
        allowlist_path=SDIST_ALLOWLIST,
        artifact_label="sdist",
        normalize_wheel_dist_info=False,
    )
