"""CLI entry point for the artemis-validation MCP server.

Admission happens once, at startup: operator credentials are turned into an
``AuthVerifier`` and an ``AuthenticationRequest``, ``create_server`` exchanges
them for a scoped authority lease, and only then are the read-only ATP tools
served over stdio.

Provenance is registered before admission is attempted, so every admission
attempt — including each bounded retry — is a child line item under this
process's ATP root rather than something reconstructed after the fact.

The server refuses every non-stdio transport (``run`` raises, and the SSE and
Streamable HTTP app factories raise), so this CLI intentionally offers no
``--http`` mode — unlike the artemis-memory entry point it mirrors.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from artemis_mcp_common.provenance import ProvenanceSession, ProvenanceUnavailable
from mcp.server.mcpserver import MCPServer
from posthog import Posthog
from posthog.mcp import instrument

from src.auth.config import AuthConfigurationError
from src.auth.verifier import AuthenticationDenied
from src.routing.authorization import AuthorizationDenied

from .server import create_server
from .wiring import (
    ValidationServerConfigurationError,
    build_auth_verifier,
    build_authentication_request,
)

_PROG = "artemis-validation-mcp"

# sysexits.h conventions, so a supervisor can tell "operator must fix the
# config" apart from "the authority refused this deployment".
_EXIT_CONFIG = 78
_EXIT_DENIED = 77

_POSTHOG_TOKEN_VAR = "POSTHOG_PROJECT_TOKEN"  # nosec B105 - variable name, not a secret
_POSTHOG_HOST_VAR = "POSTHOG_HOST"
_DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"

# Bounded retry: only the verifier being *unreachable* is worth waiting out.
_ATTEMPTS_VAR = "ARTEMIS_VALIDATION_ADMIT_ATTEMPTS"
_BACKOFF_VAR = "ARTEMIS_VALIDATION_ADMIT_BACKOFF_SECONDS"
_DEFAULT_ATTEMPTS = 5
_DEFAULT_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0


def _positive_setting(name: str, default: float, cast: type) -> float:
    """Read a tunable, falling back to the default rather than failing closed."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _build_posthog() -> Posthog | None:
    """Build the optional analytics client, or ``None`` when unconfigured.

    Constructed on call rather than at module scope: importing this module must
    stay free of side effects, matching the purity the server module is held to.
    """
    token = os.getenv(_POSTHOG_TOKEN_VAR, "").strip()
    if not token:
        if os.getenv("DEBUG"):
            print(
                f"{_POSTHOG_TOKEN_VAR} variable required by PostHog is missing or "
                "un-configured, this causes events to be silently missed. "
                f"This error stops appearing once {_POSTHOG_TOKEN_VAR} is configured",
                file=sys.stderr,
            )
        return None
    host = os.getenv(_POSTHOG_HOST_VAR, "").strip() or _DEFAULT_POSTHOG_HOST
    return Posthog(token, host=host, enable_exception_autocapture=True)


def build_stdio_server() -> MCPServer:
    """Admit this process and return the served validation server.

    Raises rather than returning a degraded server: a validation service that
    cannot prove its authority must not answer tool calls at all.
    """
    return create_server(
        verifier=build_auth_verifier(),
        authentication_request=build_authentication_request(),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description=(
            "Serve read-only canonical ATP parse, validate, and format tools "
            "over stdio. No other transport is supported."
        ),
    )
    return parser.parse_args(argv)


def _admit(provenance: ProvenanceSession) -> MCPServer | int:
    """Build the server with bounded retry, or return its denial exit code.

    Only ``AuthConfigurationError`` is retried. It means the Authstructure
    verifier itself could not be loaded — a condition a transient outage can
    clear. ``AuthenticationDenied`` and ``AuthorizationDenied`` are verdicts
    about *this* deployment's credentials and scopes; retrying them would just
    re-present the same rejected proof, so they fail immediately.

    Every attempt, retry, and terminal failure is logged as a child of the
    process ATP root and tagged ``issue`` so the outage is reviewable by
    provenance id rather than only in stderr.
    """
    attempts = int(_positive_setting(_ATTEMPTS_VAR, _DEFAULT_ATTEMPTS, int))
    backoff = _positive_setting(_BACKOFF_VAR, _DEFAULT_BACKOFF_SECONDS, float)

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            server = build_stdio_server()
        except AuthConfigurationError as error:
            elapsed = int((time.monotonic() - started) * 1000)
            final = attempt >= attempts
            prov_id = provenance.log(
                phase="admission_retry" if not final else "admission_failed",
                action_type="execute",
                target="build_stdio_server",
                status="retry" if not final else "error",
                payload_summary=(
                    f"admission attempt {attempt}/{attempts} failed: {error.code}"
                ),
                inputs={"attempt": attempt, "attempts": attempts},
                error=error.code,
                latency_ms=elapsed,
                tags=("admission", "retry" if not final else "error", "issue"),
            )
            marker = f" prov_id={prov_id}" if prov_id else ""
            if final:
                print(
                    f"{_PROG}: authentication unavailable ({error.code}) after "
                    f"{attempts} attempts{marker}",
                    file=sys.stderr,
                )
                return _EXIT_CONFIG
            delay = min(backoff * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
            print(
                f"{_PROG}: authentication unavailable ({error.code}); "
                f"retry {attempt}/{attempts - 1} in {delay:.1f}s{marker}",
                file=sys.stderr,
            )
            time.sleep(delay)
        except ValidationServerConfigurationError as error:
            provenance.log(
                phase="admission_failed",
                action_type="execute",
                target="build_stdio_server",
                status="error",
                payload_summary=str(error),
                error="missing_configuration",
                tags=("admission", "config", "issue"),
            )
            print(f"{_PROG}: {error}", file=sys.stderr)
            return _EXIT_CONFIG
        except (AuthenticationDenied, AuthorizationDenied) as denied:
            provenance.log(
                phase="admission_denied",
                action_type="execute",
                target="build_stdio_server",
                status="error",
                payload_summary=f"admission denied: {denied.code}",
                error=denied.code,
                tags=("admission", "denied", "issue"),
            )
            print(f"{_PROG}: admission denied ({denied.code})", file=sys.stderr)
            return _EXIT_DENIED
        else:
            provenance.log(
                phase="admission",
                action_type="execute",
                target="build_stdio_server",
                status="ok",
                payload_summary=f"admitted on attempt {attempt}/{attempts}",
                inputs={"attempt": attempt},
                latency_ms=int((time.monotonic() - started) * 1000),
                tags=("admission", "ok"),
            )
            return server

    # The loop either returns a server or an exit code; this is unreachable.
    raise AssertionError("unreachable admission state")


def main(argv: Sequence[str] | None = None) -> int:
    _parse_args(argv)

    provenance = ProvenanceSession(
        server_name="artemis-validation",
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

    admitted = _admit(provenance)
    if isinstance(admitted, int):
        return admitted
    server = admitted

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
            phase="atp_response",
            action_type="respond",
            target="stdio",
            status="ok",
            payload_summary="stdio transport stopped",
            tags=("atp", "response"),
        )
        if posthog is not None:
            posthog.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
