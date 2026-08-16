"""Fail-closed configuration for the unpublished Authstructure integration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .verifier import AuthVerifier


class AuthConfigurationError(Exception):
    """Authentication configuration failure with a stable safe code."""

    def __init__(self, code: str) -> None:
        del code
        self.code = "auth_verifier_unavailable"
        super().__init__(self.code)


@dataclass(frozen=True)
class AuthstructureConfig:
    """Operator-supplied public configuration for Authstructure verification."""

    url: str
    audience: str
    signer_namespace: str
    receipt_key_id: str

    @classmethod
    def from_environment(cls, environment: str) -> AuthstructureConfig:
        """Read required public fields without deriving authority from them."""

        del environment
        values = {
            "url": os.getenv("ARTEMIS_AUTHSTRUCTURE_URL", "").strip(),
            "audience": os.getenv("ARTEMIS_AUTHSTRUCTURE_AUDIENCE", "").strip(),
            "signer_namespace": os.getenv(
                "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE", ""
            ).strip(),
            "receipt_key_id": os.getenv(
                "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", ""
            ).strip(),
        }
        if not all(values.values()):
            raise AuthConfigurationError("auth_verifier_unavailable")
        return cls(**values)


def load_auth_verifier(environment: str) -> AuthVerifier:
    """Fail closed until Authstructure publishes a conformance contract."""

    AuthstructureConfig.from_environment(environment)
    raise AuthConfigurationError("auth_verifier_unavailable")
