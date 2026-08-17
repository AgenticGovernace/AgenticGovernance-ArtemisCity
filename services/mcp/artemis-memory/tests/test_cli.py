"""Configuration tests for the artemis-memory CLI, without any live database."""

from __future__ import annotations

import pytest
from artemis_memory_mcp.__main__ import build_http_server, build_stdio_server
from artemis_memory_mcp.wiring import (
    MemoryServerConfigurationError,
    build_memory_service,
)

_STDIO_VARS = ("ARTEMIS_MCP_PRINCIPAL_ID", "ARTEMIS_MCP_CAPABILITIES")
_HTTP_VARS = (
    "ARTEMIS_MCP_BEARER_TOKEN",
    "ARTEMIS_MCP_HTTP_CLIENT_ID",
    "ARTEMIS_MCP_HTTP_SUBJECT",
    "ARTEMIS_MCP_HTTP_SCOPES",
    "ARTEMIS_MCP_AUTH_ISSUER_URL",
    "ARTEMIS_MCP_RESOURCE_SERVER_URL",
)
_VALID_HTTP_VALUES = {
    "ARTEMIS_MCP_BEARER_TOKEN": "configured-token",
    "ARTEMIS_MCP_HTTP_CLIENT_ID": "artemis-mcp",
    "ARTEMIS_MCP_HTTP_SUBJECT": "memory-service",
    "ARTEMIS_MCP_HTTP_SCOPES": "artemis:memory",
    "ARTEMIS_MCP_AUTH_ISSUER_URL": "https://issuer.example.com",
    "ARTEMIS_MCP_RESOURCE_SERVER_URL": "https://resource.example.com",
}


def _clear_all(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ARTEMIS_MEMORY_DATABASE_URL", *_STDIO_VARS, *_HTTP_VARS):
        monkeypatch.delenv(name, raising=False)


def test_build_memory_service_fails_before_any_connection_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)

    with pytest.raises(
        MemoryServerConfigurationError, match="ARTEMIS_MEMORY_DATABASE_URL"
    ):
        build_memory_service()


def test_stdio_server_requires_principal_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("ARTEMIS_MCP_CAPABILITIES", "memory:write")

    with pytest.raises(
        MemoryServerConfigurationError, match="ARTEMIS_MCP_PRINCIPAL_ID"
    ):
        build_stdio_server()


def test_stdio_server_requires_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("ARTEMIS_MCP_PRINCIPAL_ID", "local-operator")

    with pytest.raises(
        MemoryServerConfigurationError, match="ARTEMIS_MCP_CAPABILITIES"
    ):
        build_stdio_server()


def test_stdio_server_builds_with_complete_local_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("ARTEMIS_MCP_PRINCIPAL_ID", "local-operator")
    monkeypatch.setenv(
        "ARTEMIS_MCP_CAPABILITIES",
        "memory:write,memory:read,memory:namespace:*",
    )

    server = build_stdio_server()

    assert server.name == "artemis-memory"


@pytest.mark.parametrize("missing_var", _HTTP_VARS)
def test_http_server_requires_every_http_variable(
    monkeypatch: pytest.MonkeyPatch, missing_var: str
) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://example/db")
    for name, value in _VALID_HTTP_VALUES.items():
        if name != missing_var:
            monkeypatch.setenv(name, value)

    with pytest.raises(MemoryServerConfigurationError, match=missing_var):
        build_http_server()


def test_http_server_builds_with_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all(monkeypatch)
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://example/db")
    for name, value in _VALID_HTTP_VALUES.items():
        monkeypatch.setenv(name, value)

    server = build_http_server()

    assert server.name == "artemis-memory"
