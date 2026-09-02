"""CLI entry point: stdio by default, authenticated Streamable HTTP with --http."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from collections.abc import Sequence

from artemis_mcp_common.gate import GovernedGate
from artemis_mcp_common.principals import (
    BearerPrincipalProvider,
    LocalPrincipalProvider,
    StaticBearerTokenVerifier,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from posthog import Posthog
from posthog.mcp import instrument as _mcp_instrument

from .server import create_memory_server
from .wiring import MemoryServerConfigurationError, build_memory_service

# Module-scope PostHog client (optional — server runs normally without it).
_POSTHOG_TOKEN = os.environ.get("POSTHOG_PROJECT_TOKEN", "")
_POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")

if _POSTHOG_TOKEN:
    _posthog: Posthog | None = Posthog(
        _POSTHOG_TOKEN,
        host=_POSTHOG_HOST,
        enable_exception_autocapture=True,
    )
else:
    _posthog = None
    if os.environ.get("DEBUG"):
        print(
            "POSTHOG_PROJECT_TOKEN variable required by PostHog is missing or "
            "un-configured, this causes events to be silently missed. "
            "This error stops appearing once POSTHOG_PROJECT_TOKEN is configured",
            file=sys.stderr,
        )

_TRANSPORT_SCOPE = "artemis:memory"

_STDIO_REQUIRED_VARS = ("ARTEMIS_MCP_PRINCIPAL_ID", "ARTEMIS_MCP_CAPABILITIES")
_HTTP_REQUIRED_VARS = (
    "ARTEMIS_MCP_BEARER_TOKEN",
    "ARTEMIS_MCP_HTTP_CLIENT_ID",
    "ARTEMIS_MCP_HTTP_SUBJECT",
    "ARTEMIS_MCP_HTTP_SCOPES",
    "ARTEMIS_MCP_AUTH_ISSUER_URL",
    "ARTEMIS_MCP_RESOURCE_SERVER_URL",
)


def _require_env(names: Sequence[str]) -> dict[str, str]:
    """Read every named variable or fail closed listing what is missing."""
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        raise MemoryServerConfigurationError(
            "missing required configuration: " + ", ".join(missing)
        )
    return {name: os.environ[name] for name in names}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="artemis-memory-mcp")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve authenticated Streamable HTTP at /mcp instead of stdio.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args(argv)


def build_stdio_server() -> MCPServer:
    """Build the server for the stdio transport, failing closed on missing config."""
    _require_env(_STDIO_REQUIRED_VARS)
    memory_service = build_memory_service()
    return create_memory_server(
        memory_service=memory_service,
        gate=GovernedGate(),
        principal_provider=LocalPrincipalProvider.from_environment().current,
    )


def build_http_server() -> MCPServer:
    """Build the server for the authenticated Streamable HTTP transport."""
    env = _require_env(_HTTP_REQUIRED_VARS)
    memory_service = build_memory_service()

    scopes = [
        scope.strip()
        for scope in env["ARTEMIS_MCP_HTTP_SCOPES"].split(",")
        if scope.strip()
    ]
    verifier = StaticBearerTokenVerifier(
        expected_token=env["ARTEMIS_MCP_BEARER_TOKEN"],
        subject=env["ARTEMIS_MCP_HTTP_SUBJECT"],
        scopes=scopes,
        client_id=env["ARTEMIS_MCP_HTTP_CLIENT_ID"],
    )
    auth = AuthSettings(
        issuer_url=env["ARTEMIS_MCP_AUTH_ISSUER_URL"],
        resource_server_url=env["ARTEMIS_MCP_RESOURCE_SERVER_URL"],
        required_scopes=[_TRANSPORT_SCOPE],
    )
    return create_memory_server(
        memory_service=memory_service,
        gate=GovernedGate(),
        principal_provider=BearerPrincipalProvider().current,
        auth=auth,
        token_verifier=verifier,
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.http:
        server = build_http_server()
        if _posthog is not None:
            _mcp_instrument(server, _posthog)
        print(
            f"artemis-memory-mcp: starting streamable-http on "
            f"{args.host}:{args.port}/mcp",
            file=sys.stderr,
        )
        try:
            server.run(
                "streamable-http",
                host=args.host,
                port=args.port,
                streamable_http_path="/mcp",
            )
        finally:
            if _posthog is not None:
                _posthog.shutdown()
    else:
        server = build_stdio_server()
        if _posthog is not None:
            _mcp_instrument(server, _posthog)

            def _on_sigterm(signum: int, frame: object) -> None:
                _posthog.shutdown()
                sys.exit(0)

            signal.signal(signal.SIGTERM, _on_sigterm)

        print("artemis-memory-mcp: starting stdio transport", file=sys.stderr)
        server.run("stdio")
        if _posthog is not None:
            _posthog.shutdown()


if __name__ == "__main__":
    main()
