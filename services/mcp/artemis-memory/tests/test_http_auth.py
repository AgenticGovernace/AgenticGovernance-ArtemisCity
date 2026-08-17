"""ASGI-level bearer-auth tests for the artemis-memory HTTP transport.

These never open a real network listener: they drive the Starlette ASGI app
directly through ``httpx.ASGITransport``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest
from artemis_mcp_common.gate import GovernedGate
from artemis_mcp_common.principals import (
    BearerPrincipalProvider,
    StaticBearerTokenVerifier,
)
from artemis_memory_mcp.server import create_memory_server
from mcp.server.auth.settings import AuthSettings

from src.memory.service import MemoryService

_EXPECTED_TOKEN = "configured-secret-token"  # nosec B105 - test-only fixture value


class _UnusedLedger:
    """A ledger that must never be touched while a request is unauthenticated."""

    def write_version(self, command):
        raise AssertionError("ledger must not be reached without authentication")

    def read(self, namespace, key):
        raise AssertionError("ledger must not be reached without authentication")

    def search(self, namespace, query, limit):
        raise AssertionError("ledger must not be reached without authentication")

    def projection_status(self, namespace, record_id):
        raise AssertionError("ledger must not be reached without authentication")

    def claim_projection(self, record_id, projection):
        raise AssertionError("ledger must not be reached without authentication")


def _build_http_server():
    service = MemoryService(_UnusedLedger(), [])
    verifier = StaticBearerTokenVerifier(
        expected_token=_EXPECTED_TOKEN,
        subject="memory-service",
        scopes=["artemis:memory", "memory:read", "memory:namespace:*"],
        client_id="artemis-mcp",
    )
    auth = AuthSettings(
        issuer_url="https://issuer.example.com",
        resource_server_url="http://127.0.0.1:8000",
        required_scopes=["artemis:memory"],
    )
    return create_memory_server(
        memory_service=service,
        gate=GovernedGate(),
        principal_provider=BearerPrincipalProvider().current,
        auth=auth,
        token_verifier=verifier,
    )


@asynccontextmanager
async def _asgi_client(server):
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client,
    ):
        yield client


_LIST_TOOLS_REQUEST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
_JSON_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected_with_401():
    server = _build_http_server()

    async with _asgi_client(server) as client:
        response = await client.post(
            "/mcp", json=_LIST_TOOLS_REQUEST, headers=_JSON_HEADERS
        )

    assert response.status_code == 401
    assert _EXPECTED_TOKEN not in response.text


@pytest.mark.asyncio
async def test_wrong_bearer_token_is_rejected_with_401():
    server = _build_http_server()

    async with _asgi_client(server) as client:
        response = await client.post(
            "/mcp",
            json=_LIST_TOOLS_REQUEST,
            headers={**_JSON_HEADERS, "Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 401
    assert _EXPECTED_TOKEN not in response.text


@pytest.mark.asyncio
async def test_valid_bearer_token_reaches_the_protocol_layer():
    server = _build_http_server()

    async with _asgi_client(server) as client:
        response = await client.post(
            "/mcp",
            json=_LIST_TOOLS_REQUEST,
            headers={**_JSON_HEADERS, "Authorization": f"Bearer {_EXPECTED_TOKEN}"},
        )

    assert response.status_code == 200
    assert _EXPECTED_TOKEN not in response.text


@pytest.mark.asyncio
async def test_protected_resource_metadata_is_published_for_mcp():
    server = _build_http_server()

    async with _asgi_client(server) as client:
        response = await client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert _EXPECTED_TOKEN not in response.text
