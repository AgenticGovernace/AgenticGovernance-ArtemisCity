"""Fail-closed configuration for the unpublished Authstructure integration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
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
        invalid_configuration = False
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
            invalid_configuration = True
        if invalid_configuration:
            raise AuthConfigurationError("auth_verifier_unavailable")

    @classmethod
    def from_environment(cls, environment: str) -> AuthstructureConfig:
        """Read required public fields without deriving authority from them."""

        del environment
        values = {
            "url": os.getenv("ARTEMIS_AUTHSTRUCTURE_URL", ""),
            "audience": os.getenv("ARTEMIS_AUTHSTRUCTURE_AUDIENCE", ""),
            "signer_namespace": os.getenv("ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE", ""),
            "receipt_key_id": os.getenv("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", ""),
        }
        if not all(values.values()):
            raise AuthConfigurationError("auth_verifier_unavailable")
        return cls(**values)

    @staticmethod
    def _validate_url(value: str) -> None:
        if not value or any(character.isspace() for character in value):
            raise ValueError
        if value.startswith("https://"):
            expected_scheme = "https"
        elif value.startswith("http://"):
            expected_scheme = "http"
        else:
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme != expected_scheme
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        authority = parsed.netloc
        if not authority or "[" in authority or "]" in authority:
            raise ValueError
        if authority.count(":") > 1:
            raise ValueError
        if ":" in authority:
            hostname, port_text = authority.rsplit(":", 1)
            if re.fullmatch(r"[0-9]{1,5}", port_text) is None:
                raise ValueError
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ValueError
        else:
            hostname = authority

        if re.fullmatch(r"[0-9.]+", hostname):
            octets = hostname.split(".")
            if (
                len(octets) != 4
                or any(not octet for octet in octets)
                or any(len(octet) > 1 and octet.startswith("0") for octet in octets)
                or any(int(octet) > 255 for octet in octets)
            ):
                raise ValueError
        else:
            labels = hostname.split(".")
            if len(hostname) > 253 or any(
                not label
                or len(label) > 63
                or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                is None
                for label in labels
            ):
                raise ValueError from None

        if expected_scheme == "http" and hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError


def load_auth_verifier(environment: str) -> AuthVerifier:
    """Fail closed until Authstructure publishes a conformance contract."""

    AuthstructureConfig.from_environment(environment)
    raise AuthConfigurationError("auth_verifier_unavailable")
