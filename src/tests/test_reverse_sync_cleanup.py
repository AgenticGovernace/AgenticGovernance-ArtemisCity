"""Characterization tests for the reviewed reverse-sync cleanup manifest."""

from __future__ import annotations

import hashlib
import subprocess
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    ROOT / "docs" / "audits" / "2026-08-16-reverse-sync-72cf776-path-manifest.yaml"
)
HOLD_PATH = (
    ROOT / "docs" / "audits" / "2026-08-16-reverse-sync-72cf776-removal-hold.yaml"
)
SOURCE_COMMIT = "72cf776a69b260d4bcc2c811179d49dc34dbbf0d"
EXPECTED_MANIFEST_SHA256 = (
    "60d558d7d4f2881fed87a15d61b4ad018892aba8f2690d91f172b5be3b94914e"
)
EXPECTED_HOLD_NAME = "reverse-sync-72cf776-removal-hold"
EXPECTED_HOLD_DATE = "2026-08-16"
EXPECTED_SELECTION_RULE = "classification == REMOVE_REVERSE_SYNC and source_status == A"
EXPECTED_HELD_COUNT = 217
EXPECTED_HELD_LIST_SHA256 = (
    "2f07edf48b8a82bd10a35826c3df009d4d60a3f54593db4a424d309d644b1f3b"
)
EXPECTED_HELD_LIST_NUL_SHA256 = (
    "3c9f34fb66d414f4e76736d6017297883ada63775ceba71e94cc406ef62e79c3"
)
EXPECTED_DEFERRED_RESTORATION_COUNT = 19
EXPECTED_DEFERRED_RESTORATION_SHA256 = (
    "3852300a2ea1a41454b158db6e77f3abed5f649f2d4c173405bc33fe27c933ae"
)
EXPECTED_DEFERRED_RESTORATION_PATHS = [
    ".devcontainer/devcontainer.json",
    ".github/workflows/promote.yml",
    ".vscode/settings.json",
    "app/web/frontend/.env.example",
    "benchmarks/bench_memory_ops.py",
    "examples/README.md",
    "examples/governance_demo/README.md",
    "examples/governance_demo/run.py",
    "examples/minimal_deployment/README.md",
    "examples/minimal_deployment/run.py",
    "examples/multi_agent_workflow/README.md",
    "examples/multi_agent_workflow/run.py",
    "sandbox_city/_Index_of_sandbox_city.md",
    "sandbox_city/index.md",
    "sandbox_city/semantic_zones.md",
    "app/scripts/data/vector_store.db",
    "supabase/migrations/artemis.sql",
    "monitoring/alerts.yml",
    "monitoring/prometheus.yml",
]
EXPECTED_REASON = (
    "Keep reverse-sync comparison material until merge and reviews are complete."
)
EXPECTED_SCOPE_STATEMENT = (
    "This hold authorizes no deletion, restore, move, rename, or content rewrite."
)
EXPECTED_QUARANTINE_RULE = (
    "Retained paths are evidence only and receive no runtime, import, routing, "
    "test-collection, or release authority merely by being tracked."
)
EXPECTED_RELEASE_CONDITIONS = [
    "relevant_merge_completed",
    "review_signoffs_recorded",
    "fresh_explicit_user_authorization",
    "source_manifest_hash_unchanged",
    "held_list_count_and_digests_unchanged",
    "hold_presence_gate_green",
    "release_package_gate_green",
]
EXPECTED_EXPANDED_STATUS_COUNTS = {"A": 293, "M": 18, "D": 60}
EXPECTED_CLASSIFICATION_COUNTS = {
    "KEEP_AUTHORITATIVE": 21,
    "KEEP_COMPATIBILITY": 1,
    "REMOVE_REVERSE_SYNC": 221,
    "REVIEW_SEPARATELY": 79,
    "ALREADY_CORRECTED": 49,
}


def load_reverse_sync_manifest() -> dict[str, object]:
    """Return the committed reverse-sync cleanup manifest."""

    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def load_reverse_sync_hold() -> dict[str, object]:
    """Return the committed reverse-sync hold record."""

    return yaml.safe_load(HOLD_PATH.read_text(encoding="utf-8"))


def _manifest_sha256() -> str:
    return hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()


def _canonical_line_sha256(paths: list[str]) -> str:
    payload = "".join(f"{path}\n" for path in paths).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_nul_sha256(paths: list[str]) -> str:
    payload = b"".join(f"{path}\0".encode("utf-8") for path in paths)
    return hashlib.sha256(payload).hexdigest()


def _expanded_source_delta() -> list[tuple[str, str]]:
    result = subprocess.run(
        [
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-M",
            SOURCE_COMMIT,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    expanded: list[tuple[str, str]] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            expanded.append((parts[1], "D"))
            expanded.append((parts[2], "A"))
            continue
        expanded.append((parts[1], status))
    return expanded


def _held_reverse_sync_paths(manifest: dict[str, object]) -> list[str]:
    manifest_paths = manifest["paths"]
    return [
        entry["path"]
        for entry in manifest_paths
        if entry["classification"] == "REMOVE_REVERSE_SYNC"
        and entry["source_status"] == "A"
    ]


def _tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    return {path.decode("utf-8") for path in result.stdout.split(b"\0") if path}


def test_reverse_sync_manifest_matches_the_reviewed_source_commit() -> None:
    manifest = load_reverse_sync_manifest()
    manifest_paths = manifest["paths"]

    assert manifest["source_commit"]["sha"] == SOURCE_COMMIT
    assert _manifest_sha256() == EXPECTED_MANIFEST_SHA256

    manifest_pairs = [
        (entry["path"], entry["source_status"]) for entry in manifest_paths
    ]
    source_pairs = _expanded_source_delta()

    assert manifest_pairs == source_pairs

    expanded_paths = [path for path, _status in manifest_pairs]
    expanded_status_counts = Counter(status for _path, status in manifest_pairs)
    classification_counts = Counter(entry["classification"] for entry in manifest_paths)

    assert expanded_status_counts == EXPECTED_EXPANDED_STATUS_COUNTS
    assert classification_counts == EXPECTED_CLASSIFICATION_COUNTS
    assert len(expanded_paths) == len(set(expanded_paths)) == 371


def test_reverse_sync_hold_freezes_the_reviewed_removal_slice() -> None:
    hold = load_reverse_sync_hold()
    manifest = load_reverse_sync_manifest()
    held_paths = _held_reverse_sync_paths(manifest)
    tracked_paths = _tracked_paths()

    missing_tracked = [path for path in held_paths if path not in tracked_paths]
    missing_files = [path for path in held_paths if not (ROOT / path).exists()]
    lexical_violations = [
        path
        for path in held_paths
        if Path(path).is_absolute() or ".." in Path(path).parts
    ]

    def _violation(prefix: str, paths: list[str]) -> str:
        sample = ", ".join(paths[:5])
        return f"REVERSE_SYNC_HOLD_VIOLATION {prefix}: total={len(paths)} sample=[{sample}]"

    assert hold["metadata"] == {
        "name": EXPECTED_HOLD_NAME,
        "hold_version": 1,
        "hold_date": EXPECTED_HOLD_DATE,
        "owner_repository": "Artemis_City",
        "status": "active",
    }
    assert hold["source_manifest"] == {
        "path": "docs/audits/2026-08-16-reverse-sync-72cf776-path-manifest.yaml",
        "sha256": EXPECTED_MANIFEST_SHA256,
        "source_commit": SOURCE_COMMIT,
    }

    assert len(held_paths) == EXPECTED_HELD_COUNT
    assert _canonical_line_sha256(held_paths) == EXPECTED_HELD_LIST_SHA256
    assert _canonical_nul_sha256(held_paths) == EXPECTED_HELD_LIST_NUL_SHA256
    assert hold["held_paths"] == {
        "selection_rule": EXPECTED_SELECTION_RULE,
        "count": EXPECTED_HELD_COUNT,
        "line_encoding": "manifest order, UTF-8, one path per line, terminal LF",
        "line_sha256": EXPECTED_HELD_LIST_SHA256,
        "nul_encoding": "manifest order, UTF-8, NUL after each path",
        "nul_sha256": EXPECTED_HELD_LIST_NUL_SHA256,
    }
    assert hold["deferred_restorations"] == {
        "count": EXPECTED_DEFERRED_RESTORATION_COUNT,
        "ordered_paths": EXPECTED_DEFERRED_RESTORATION_PATHS,
        "line_encoding": "brief order, UTF-8, one path per line, terminal LF",
        "line_sha256": EXPECTED_DEFERRED_RESTORATION_SHA256,
    }
    assert hold["reason"] == EXPECTED_REASON
    assert hold["scope"] == {
        "statement": EXPECTED_SCOPE_STATEMENT,
        "authorizes_deletion": False,
        "authorizes_restore": False,
        "authorizes_move": False,
        "authorizes_rename": False,
        "authorizes_content_rewrite": False,
    }
    assert hold["quarantine_rule"] == EXPECTED_QUARANTINE_RULE

    release_conditions = hold["release_conditions"]
    assert [item["key"] for item in release_conditions] == EXPECTED_RELEASE_CONDITIONS
    assert all(item["satisfied"] is False for item in release_conditions)
    assert hold["review_signoffs"] == []

    assert not lexical_violations, _violation("lexical-paths", lexical_violations)
    assert not missing_tracked, _violation("missing-tracked", missing_tracked)
    assert not missing_files, _violation("missing-files", missing_files)
