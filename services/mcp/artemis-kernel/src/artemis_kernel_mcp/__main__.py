"""CLI entry point for the artemis-kernel MCP server."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from artemis_mcp_common.provenance import ProvenanceSession, ProvenanceUnavailable
from posthog import Posthog
from posthog.mcp import instrument

from mcp.server.mcpserver import MCPServer

from .server import create_server
from .wiring import KernelServerConfigurationError, build_task_store

_PROG = "artemis-kernel-mcp"
_SERVER_NAME = "artemis-kernel"
_EXIT_CONFIG = 78

_POSTHOG_TOKEN_VAR = "POSTHOG_PROJECT_TOKEN"
_POSTHOG_HOST_VAR = "POSTHOG_HOST"
_DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"


def _build_posthog() -> Posthog | None:
    token = os.getenv(_POSTHOG_TOKEN_VAR, "").strip()
    if not token:
        return None
    host = os.getenv(_POSTHOG_HOST_VAR, "").strip() or _DEFAULT_POSTHOG_HOST
    return Posthog(token, host=host, enable_exception_autocapture=True)


def build_stdio_server() -> MCPServer:
    """Build the Kernel server over the operator-configured task store."""
    return create_server(service=build_task_store())


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Serve Artemis City Kernel task tools over stdio.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    _parse_args(argv)

    provenance = ProvenanceSession(
        server_name=_SERVER_NAME,
        workspace=str(Path(__file__).resolve().parents[2]),
    )
    try:
        registered = provenance.register()
    except ProvenanceUnavailable as error:
        print(f"{_PROG}: {error}", file=sys.stderr)
        return _EXIT_CONFIG
    if not registered:
        print(
            f"{_PROG}: provenance service unavailable at {provenance.service_url}; "
            "continuing without provenance (set PROVENANCE_STRICT=1 to refuse)",
            file=sys.stderr,
        )

    try:
        server = build_stdio_server()
    except KernelServerConfigurationError as error:
        provenance.log(
            phase="startup_failed", action_type="execute", target="build_stdio_server",
            status="error", payload_summary=str(error), tags=("startup", "issue"),
        )
        print(f"{_PROG}: {error}", file=sys.stderr)
        return _EXIT_CONFIG

    provenance.log(
        phase="startup", action_type="execute", target="build_stdio_server",
        status="ok", payload_summary="kernel server built", tags=("startup", "ok"),
    )

    posthog = _build_posthog()
    if posthog is not None:
        instrument(server, posthog)

        def _on_sigterm(signum: int, frame: object) -> None:
            del signum, frame
            posthog.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _on_sigterm)

    print(f"{_PROG}: starting stdio transport", file=sys.stderr)
    try:
        server.run("stdio")
    finally:
        provenance.log(
            phase="atp_response", action_type="respond", target="stdio",
            status="ok", payload_summary="stdio transport stopped",
            tags=("atp", "response"),
        )
        if posthog is not None:
            posthog.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
