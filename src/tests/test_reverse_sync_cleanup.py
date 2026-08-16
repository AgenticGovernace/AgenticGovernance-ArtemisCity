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
SOURCE_COMMIT = "72cf776a69b260d4bcc2c811179d49dc34dbbf0d"
EXPECTED_MANIFEST_SHA256 = (
    "60d558d7d4f2881fed87a15d61b4ad018892aba8f2690d91f172b5be3b94914e"
)
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


def _manifest_sha256() -> str:
    return hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()


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


def test_reverse_sync_manifest_matches_the_reviewed_source_commit() -> None:
    manifest = load_reverse_sync_manifest()
    manifest_paths = manifest["paths"]

    assert manifest["source_commit"]["sha"] == SOURCE_COMMIT
    assert _manifest_sha256() == EXPECTED_MANIFEST_SHA256

    manifest_pairs = [
        (entry["path"], entry["source_status"])
        for entry in manifest_paths
    ]
    source_pairs = _expanded_source_delta()

    assert manifest_pairs == source_pairs

    expanded_paths = [path for path, _status in manifest_pairs]
    expanded_status_counts = Counter(status for _path, status in manifest_pairs)
    classification_counts = Counter(
        entry["classification"] for entry in manifest_paths
    )

    assert expanded_status_counts == EXPECTED_EXPANDED_STATUS_COUNTS
    assert classification_counts == EXPECTED_CLASSIFICATION_COUNTS
    assert len(expanded_paths) == len(set(expanded_paths)) == 371
