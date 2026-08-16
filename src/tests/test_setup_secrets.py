"""Behavioral tests for the repository environment provisioner."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_LAYER = "src/Artemis Agentic Memory Layer"


def _copy_provisioner_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "repo"
    fixture.mkdir()
    shutil.copy2(REPO_ROOT / "setup_secrets.sh", fixture / "setup_secrets.sh")

    for relative in (
        ".env.example",
        "app/api/.env.example",
        "src/.env.example",
        f"{MEMORY_LAYER}/.env.example",
    ):
        source = REPO_ROOT / relative
        target = fixture / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return fixture


def _run(
    fixture: Path, *args: str, input_text: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "setup_secrets.sh", *args],
        cwd=fixture,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _env_value(path: Path, key: str) -> str:
    for line in path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def test_sync_backfills_every_runtime_template_and_check_detects_drift(
    tmp_path: Path,
) -> None:
    fixture = _copy_provisioner_fixture(tmp_path)
    (fixture / ".env").write_text(
        "MCP_API_KEY=keep-mcp\n"
        "ARTEMIS_API_KEY_DEFAULT=keep-ts:admin:read,write\n"
        "\n"
    )
    (fixture / "app/api").mkdir(parents=True, exist_ok=True)
    (fixture / "app/api/.env").write_text("API_PORT=4999\n")
    (fixture / "src").mkdir(exist_ok=True)
    (fixture / "src/.env").write_text("MCP_API_KEY=stale-mcp\n")

    result = _run(fixture, input_text="y\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _env_value(fixture / ".env", "MCP_API_KEY") == "keep-mcp"
    assert _env_value(fixture / "app/api/.env", "API_PORT") == "4999"
    assert _env_value(fixture / "app/api/.env", "MCP_API_KEY") == "keep-mcp"
    assert _env_value(fixture / "src/.env", "MCP_API_KEY") == "keep-mcp"
    assert _env_value(fixture / ".env", "ARTEMIS_HEBBIAN_ROUTING") == "1"
    assert _env_value(fixture / "app/api/.env", "EXO_READ_TIMEOUT_SECONDS") == "900"
    assert _env_value(fixture / "src/.env", "ARTEMIS_VECTOR_BACKEND") == "sqlite"
    assert _env_value(fixture / f"{MEMORY_LAYER}/.env", "OBSIDIAN_CA_CERT") == ""
    assert stat.S_IMODE((fixture / ".env").stat().st_mode) == 0o600

    check = _run(fixture, "--check")
    assert check.returncode == 0, check.stdout + check.stderr

    src_env = fixture / "src/.env"
    src_env.write_text(
        "\n".join(
            line
            for line in src_env.read_text().splitlines()
            if not line.startswith("ARTEMIS_VECTOR_BACKEND=")
        )
        + "\n"
    )
    drift = _run(fixture, "--check")
    assert drift.returncode == 1
    assert "ARTEMIS_VECTOR_BACKEND" in drift.stdout


def test_regenerate_rotates_owned_secrets_and_propagates_them(tmp_path: Path) -> None:
    fixture = _copy_provisioner_fixture(tmp_path)
    for relative in (".env", "app/api/.env", "src/.env", f"{MEMORY_LAYER}/.env"):
        target = fixture / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "MCP_API_KEY=old-mcp\n"
            "FASTAPI_API_KEY=old-fastapi\n"
            "ARTEMIS_API_KEY_DEFAULT=old-ts:admin:read,write,delete,admin\n"
            "REDIS_PASSWORD=old-redis\n"
            "QDRANT_API_KEY=old-qdr\n"
            "GRAFANA_PASSWORD=old-grafana\n"
        )

    result = _run(fixture, "--regenerate")

    assert result.returncode == 0, result.stdout + result.stderr
    rotated_mcp = _env_value(fixture / ".env", "MCP_API_KEY")
    rotated_ts = _env_value(fixture / ".env", "ARTEMIS_API_KEY_DEFAULT")
    assert rotated_mcp and rotated_mcp != "old-mcp"
    assert rotated_ts and rotated_ts != "old-ts:admin:read,write,delete,admin"
    assert _env_value(fixture / "app/api/.env", "MCP_API_KEY") == rotated_mcp
    assert _env_value(fixture / "src/.env", "MCP_API_KEY") == rotated_mcp
    assert _env_value(fixture / f"{MEMORY_LAYER}/.env", "MCP_API_KEY") == rotated_mcp
    assert _env_value(fixture / ".env", "REDIS_PASSWORD") != "old-redis"
    assert _env_value(fixture / ".env", "QDRANT_API_KEY") != "old-qdr"
    assert _env_value(fixture / ".env", "GRAFANA_PASSWORD") != "old-grafana"
