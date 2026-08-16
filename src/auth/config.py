"""Fail-closed configuration for the unpublished Authstructure integration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

from .verifier import AuthVerifier

_CONFIG_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}\Z")


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

    def __post_init__(self) -> None:
        try:
            self._validate_url(self.url)
            for value in (
                self.audience,
                self.signer_namespace,
                self.receipt_key_id,
            ):
                if _CONFIG_IDENTIFIER.fullmatch(value) is None:
                    raise ValueError
        # Configuration parsing can fail through URL, port, host, or type
        # validation; no rejected operator value may enter the safe error.
        except Exception:  # noqa: BLE001
            raise AuthConfigurationError("auth_verifier_unavailable") from None

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

    @staticmethod
    def _validate_url(value: str) -> None:
        if not value or any(character.isspace() for character in value):
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError

        hostname = parsed.hostname
        try:
            ip_address(hostname)
        except ValueError:
            labels = hostname.split(".")
            if len(hostname) > 253 or any(
                not label
                or len(label) > 63
                or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                is None
                for label in labels
            ):
                raise ValueError from None

        if parsed.scheme == "http" and hostname.lower() not in {
            "localhost",
            "127.0.0.1",
        }:
            raise ValueError


def load_auth_verifier(environment: str) -> AuthVerifier:
    """Fail closed until Authstructure publishes a conformance contract."""

    AuthstructureConfig.from_environment(environment)
    raise AuthConfigurationError("auth_verifier_unavailable")
