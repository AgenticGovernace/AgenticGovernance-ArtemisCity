"""Behavioral tests for the repository environment provisioner."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_LAYER = "src/Artemis Agentic Memory Layer"


AUTHSTRUCTURE_CONFIG = (
    "ARTEMIS_AUTHSTRUCTURE_URL=https://auth.example.test/verify\n"
    "ARTEMIS_AUTHSTRUCTURE_AUDIENCE=artemis-city\n"
    "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE=artemis-signer\n"
    "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID=artemis-key-1\n"
)


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

    root_example = fixture / ".env.example"
    example_lines = root_example.read_text().splitlines()
    updated_lines = []
    for line in example_lines:
        if line.startswith("ARTEMIS_AUTHSTRUCTURE_URL="):
            updated_lines.append(
                "ARTEMIS_AUTHSTRUCTURE_URL=https://auth.example.test/verify"
            )
        elif line.startswith("ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE="):
            updated_lines.append(
                "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE=artemis-signer"
            )
        elif line.startswith("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID="):
            updated_lines.append(
                "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID=artemis-key-1"
            )
        else:
            updated_lines.append(line)
    root_example.write_text("\n".join(updated_lines) + "\n")
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


def _has_active_declaration(path: Path, key: str) -> bool:
    """Return whether an environment file declares a key, even when blank."""
    return any(line.startswith(f"{key}=") for line in path.read_text().splitlines())


def test_sync_backfills_every_runtime_template_and_check_detects_drift(
    tmp_path: Path,
) -> None:
    fixture = _copy_provisioner_fixture(tmp_path)
    (fixture / ".env").write_text(
        AUTHSTRUCTURE_CONFIG
        + "MCP_API_KEY=keep-mcp\n"
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
        content = (
            AUTHSTRUCTURE_CONFIG
            if relative == ".env"
            else ""
        ) + (
            "MCP_API_KEY=old-mcp\n"
            "FASTAPI_API_KEY=old-fastapi\n"
            "ARTEMIS_API_KEY_DEFAULT=old-ts:admin:read,write,delete,admin\n"
            "REDIS_PASSWORD=old-redis\n"
            "QDRANT_API_KEY=old-qdr\n"
            "GRAFANA_PASSWORD=old-grafana\n"
        )
        target.write_text(content)

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


def test_sync_preserves_operator_memory_database_urls(tmp_path: Path) -> None:
    """Sync must not replace database endpoints supplied by the operator."""
    fixture = _copy_provisioner_fixture(tmp_path)
    (fixture / ".env").write_text(
        AUTHSTRUCTURE_CONFIG
        + "ARTEMIS_MEMORY_DATABASE_URL=postgresql://runtime-operator/db\n"
        "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=postgresql://migration-operator/db\n"
    )
    (fixture / "src").mkdir(exist_ok=True)
    (fixture / "src/.env").write_text(
        "ARTEMIS_MEMORY_DATABASE_URL=postgresql://runtime-operator/db\n"
        "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=postgresql://migration-operator/db\n"
    )

    result = _run(fixture, input_text="y\ny\n")

    assert result.returncode == 0, result.stdout + result.stderr
    for relative in (".env", "src/.env"):
        env_file = fixture / relative
        assert _env_value(env_file, "ARTEMIS_MEMORY_DATABASE_URL") == (
            "postgresql://runtime-operator/db"
        )
        assert _env_value(env_file, "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL") == (
            "postgresql://migration-operator/db"
        )


def test_first_setup_leaves_memory_database_urls_blank(tmp_path: Path) -> None:
    """New environment files must not fabricate a database endpoint."""
    fixture = _copy_provisioner_fixture(tmp_path)
    (fixture / ".env").write_text(AUTHSTRUCTURE_CONFIG)

    result = _run(fixture, input_text="y\ny\ny\n")

    assert result.returncode == 0, result.stdout + result.stderr
    for relative in (".env", "src/.env", "app/api/.env"):
        env_file = fixture / relative
        assert _has_active_declaration(env_file, "ARTEMIS_MEMORY_DATABASE_URL")
        assert _env_value(env_file, "ARTEMIS_MEMORY_DATABASE_URL") == ""

    for relative in (".env", "src/.env"):
        env_file = fixture / relative
        assert _has_active_declaration(
            env_file, "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL"
        )
        assert _env_value(env_file, "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL") == ""

    express_env = fixture / "app/api/.env"
    assert _env_value(express_env, "ARTEMIS_MEMORY_BACKEND") == "legacy"
    assert _env_value(express_env, "ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS") == "10"
    assert _env_value(express_env, "ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS") == "5000"
    assert not _has_active_declaration(
        express_env, "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL"
    )


def test_regenerate_preserves_operator_memory_database_urls(tmp_path: Path) -> None:
    """Rotating owned secrets must not rotate operator database endpoints."""
    fixture = _copy_provisioner_fixture(tmp_path)
    for relative in (".env", "src/.env"):
        env_file = fixture / relative
        env_file.parent.mkdir(parents=True, exist_ok=True)
        content = (
            AUTHSTRUCTURE_CONFIG
            if relative == ".env"
            else ""
        ) + (
            "ARTEMIS_MEMORY_DATABASE_URL=postgresql://runtime-operator/db\n"
            "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=postgresql://migration-operator/db\n"
        )
        env_file.write_text(content)

    result = _run(fixture, "--regenerate", input_text="y\ny\n")

    assert result.returncode == 0, result.stdout + result.stderr
    for relative in (".env", "src/.env"):
        env_file = fixture / relative
        assert _env_value(env_file, "ARTEMIS_MEMORY_DATABASE_URL") == (
            "postgresql://runtime-operator/db"
        )
        assert _env_value(env_file, "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL") == (
            "postgresql://migration-operator/db"
        )



def test_pytest_startup_clears_live_memory_database_urls_before_import() -> None:
    """A subprocess must lose inherited live endpoints before application import."""
    environment = {
        "ARTEMIS_MEMORY_BACKEND": "neon",
        "ARTEMIS_MEMORY_DATABASE_URL": "postgresql://live-runtime/db",
        "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL": "postgresql://live-migration/db",
        "OBSIDIAN_API_KEY": "operator-secret-must-not-survive-pytest-startup",
        "ARTEMIS_TASK5_PYTEST_GUARD_PROBE": "1",
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "src/tests/test_setup_secrets.py::test_pytest_environment_guard_probe",
            "-q",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, **environment},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_pytest_environment_guard_probe() -> None:
    """Assert the subprocess-only pytest startup contract before app imports."""
    if os.getenv("ARTEMIS_TASK5_PYTEST_GUARD_PROBE") != "1":
        return

    assert "ARTEMIS_MEMORY_DATABASE_URL" not in os.environ
    assert "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL" not in os.environ
    assert "OBSIDIAN_API_KEY" not in os.environ
    from src.integration import memory_store_factory

    assert memory_store_factory.create_sql_memory_store() is None
