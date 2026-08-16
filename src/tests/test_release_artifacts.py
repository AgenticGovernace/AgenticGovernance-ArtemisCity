"""Characterization tests for Python release artifact scope."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
WHEEL_ALLOWLIST = ROOT / "config" / "release" / "python-wheel-files.v1.txt"
SDIST_ALLOWLIST = ROOT / "config" / "release" / "python-sdist-files.v1.txt"
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


def test_allowlist_comparator_accepts_normalized_wheel_dist_info(tmp_path: Path) -> None:
    allowlist = tmp_path / "wheel-allowlist.txt"
    allowlist.write_text(
        "\n".join(
            [
                "app/__init__.py",
                "{dist_info}/METADATA",
                "{dist_info}/WHEEL",
                "{dist_info}/RECORD",
            ]
        )
        + "\n",
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


def test_allowlist_comparator_rejects_placeholder_allowlist(tmp_path: Path) -> None:
    allowlist = tmp_path / "wheel-allowlist.txt"
    allowlist.write_text("", encoding="utf-8")

    with pytest.raises(AssertionError, match="TASK_6_RELEASE_ALLOWLIST_MISMATCH"):
        _assert_members_match_allowlist(
            member_names=["app/__init__.py"],
            allowlist_path=allowlist,
            artifact_label="wheel",
            normalize_wheel_dist_info=True,
        )


@pytest.fixture(scope="module")
def built_release_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
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
        if path.parts[:2] == ("src", "Kernel") and member_name != "src/Kernel/__init__.py":
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
        "TASK_6_RELEASE_ALLOWLIST_MISSING: "
        f"{artifact_label} allowlist {_display_path(path)} "
        "must be committed in Task 6 before release contents can be frozen."
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

    normalized_members = sorted(
        {
            _normalize_allowlist_member(
                member_name,
                normalize_wheel_dist_info=normalize_wheel_dist_info,
            )
            for member_name in member_names
        }
    )
    allowlist_members = sorted(
        set(
            _read_allowlist(
                allowlist_path,
                normalize_wheel_dist_info=normalize_wheel_dist_info,
            )
        )
    )

    missing_from_artifact = sorted(set(allowlist_members) - set(normalized_members))
    unexpected_in_artifact = sorted(set(normalized_members) - set(allowlist_members))

    assert normalized_members == allowlist_members, (
        "TASK_6_RELEASE_ALLOWLIST_MISMATCH: "
        f"{artifact_label} members differ from {_display_path(allowlist_path)}; "
        f"missing_from_artifact={missing_from_artifact[:20]}, "
        f"unexpected_in_artifact={unexpected_in_artifact[:20]}."
    )


def test_wheel_rejects_forbidden_release_members(
    built_release_artifacts: dict[str, Path],
) -> None:
    violations = _artifact_scope_violations(
        _artifact_members(built_release_artifacts["wheel"])
    )
    assert not violations, (
        "TASK_6_RELEASE_ARTIFACT_SCOPE: wheel contains forbidden payloads "
        "before release narrowing: "
        f"{violations[:40]}."
    )


def test_sdist_rejects_forbidden_release_members(
    built_release_artifacts: dict[str, Path],
) -> None:
    violations = _artifact_scope_violations(
        _artifact_members(built_release_artifacts["sdist"])
    )
    assert not violations, (
        "TASK_6_RELEASE_ARTIFACT_SCOPE: sdist contains forbidden payloads "
        "before release narrowing: "
        f"{violations[:40]}."
    )


def test_wheel_allowlist_contract_is_present(
    built_release_artifacts: dict[str, Path],
) -> None:
    _assert_members_match_allowlist(
        member_names=_artifact_members(built_release_artifacts["wheel"]),
        allowlist_path=WHEEL_ALLOWLIST,
        artifact_label="wheel",
        normalize_wheel_dist_info=True,
    )


def test_sdist_allowlist_contract_is_present(
    built_release_artifacts: dict[str, Path],
) -> None:
    _assert_members_match_allowlist(
        member_names=_artifact_members(built_release_artifacts["sdist"]),
        allowlist_path=SDIST_ALLOWLIST,
        artifact_label="sdist",
        normalize_wheel_dist_info=False,
    )
