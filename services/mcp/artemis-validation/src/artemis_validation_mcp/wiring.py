"""Environment wiring for the artemis-validation MCP server.

``server.create_server`` is a pure factory: it accepts an already-built
``AuthVerifier`` and ``AuthenticationRequest`` and never reads the process
environment. The test suite enforces that purity — it asserts the server
module's source contains no ``os.getenv``/``os.environ``, no principal loader,
and exposes neither ``main`` nor a module-level ``server``.

This module is where that impurity is allowed to live. Nothing here runs at
import time; every environment read happens inside a called function so that
importing the package stays free of side effects.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import Final, Literal

from src.auth.config import load_auth_verifier
from src.auth.verifier import AuthenticationRequest, AuthVerifier

# Admission is a startup handshake over stdio. ``_admit_stdio_authority``
# rejects any other transport outright, so these are fixed rather than tunable.
_TRANSPORT: Final[Literal["stdio"]] = "stdio"
_AUTHORITY = "artemis-validation"
_RAW_TARGET = b"mcp://stdio/artemis-validation"
_ADMISSION_METHOD = "initialize"

# The operator's transient proof rides under a header alias that the
# Authstructure boundary recognises as credential material, so its
# leak-detection scan will deny any receipt that echoes it back.
_PROOF_HEADER = "authorization"
_PROOF_SCHEME = "Bearer"
_PROOF_VAR = "ARTEMIS_MCP_BEARER_TOKEN"

_ENVIRONMENT_VAR = "ARTEMIS_ENV"
_DEFAULT_ENVIRONMENT = "dev"

# Public, non-secret operator configuration consumed by ``AuthstructureConfig``.
# Naming the missing ones is safe; their values are never echoed.
_VERIFIER_CONFIG_VARS = (
    "ARTEMIS_AUTHSTRUCTURE_URL",
    "ARTEMIS_AUTHSTRUCTURE_AUDIENCE",
    "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE",
    "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID",
)


class ValidationServerConfigurationError(RuntimeError):
    """Raised when required deployment configuration is missing or invalid."""


def _require_env(names: Sequence[str]) -> None:
    """Fail closed listing which variables are absent, never their values."""
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        raise ValidationServerConfigurationError(
            "missing required configuration: " + ", ".join(missing)
        )


def build_auth_verifier() -> AuthVerifier:
    """Load the canonical Authstructure verifier from operator configuration.

    The four ``ARTEMIS_AUTHSTRUCTURE_*`` variables are checked here only so a
    misconfigured deployment gets an actionable message; ``load_auth_verifier``
    re-reads and validates them itself and remains the single source of truth.

    Note that ``load_auth_verifier`` is currently a deliberate fail-closed stub
    that raises ``AuthConfigurationError("auth_verifier_unavailable")`` until
    Authstructure publishes a conformance contract. Substituting a permissive
    verifier here would hand out root authority on operator-declared identity,
    which is exactly what this service is built to refuse.
    """
    _require_env(_VERIFIER_CONFIG_VARS)
    environment = os.getenv(_ENVIRONMENT_VAR, "").strip() or _DEFAULT_ENVIRONMENT
    return load_auth_verifier(environment)


def build_authentication_request() -> AuthenticationRequest:
    """Present the operator's transient stdio proof for verification.

    The request id is minted fresh per process start rather than read from the
    environment. Authstructure binds each receipt to the request id it was
    issued against, so an unguessable per-process value makes a captured
    receipt useless on the next restart.
    """
    _require_env((_PROOF_VAR,))
    proof = os.environ[_PROOF_VAR].strip()
    return AuthenticationRequest(
        transport=_TRANSPORT,
        request_id=f"request:{_AUTHORITY}:{uuid.uuid4()}",
        method=_ADMISSION_METHOD,
        authority=_AUTHORITY,
        raw_target=_RAW_TARGET,
        headers={_PROOF_HEADER: (f"{_PROOF_SCHEME} {proof}",)},
        body=b"",
    )
