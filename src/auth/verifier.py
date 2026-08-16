"""Transport-neutral authentication verification and authority construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol

from .contracts import AuthorityContextV1, AuthReceiptV1, VerifiedPartyV1

_AUTHENTICATION_DENIAL_CODES = frozenset(
    {
        "authentication_rejected",
        "auth_verifier_unavailable",
        "invalid_signature_metadata",
        "principal_expired",
        "receipt_audience_mismatch",
        "receipt_canonicalization_mismatch",
        "receipt_hash_mismatch",
        "receipt_request_mismatch",
        "receipt_time_invalid",
        "unsupported_receipt_version",
    }
)


@dataclass(frozen=True, repr=False)
class AuthenticationRequest:
    """Transient transport proof presented only to an authentication verifier."""

    transport: Literal["http", "stdio", "cli"]
    request_id: str
    method: str
    authority: str
    raw_target: bytes
    headers: Mapping[str, tuple[str, ...]] = field(repr=False)
    body: bytes = field(repr=False)

    def __post_init__(self) -> None:
        invalid_headers = False
        try:
            if not isinstance(self.headers, Mapping):
                raise TypeError
            copied_headers: dict[str, tuple[str, ...]] = {}
            for key, values in self.headers.items():
                if not isinstance(key, str) or not isinstance(values, tuple):
                    raise TypeError
                if any(not isinstance(value, str) for value in values):
                    raise TypeError
                copied_headers[key] = tuple(values)
            object.__setattr__(self, "headers", MappingProxyType(copied_headers))
        # Custom mappings may fail while iterating. Their potentially secret
        # exception details must not escape this transient boundary.
        except Exception:  # noqa: BLE001
            invalid_headers = True
        if invalid_headers:
            raise ValueError("invalid_authentication_request_headers")


class AuthenticationDenied(Exception):
    """Authentication failure carrying only a stable, credential-free code."""

    def __init__(self, code: str) -> None:
        safe_code = (
            code if code in _AUTHENTICATION_DENIAL_CODES else "authentication_rejected"
        )
        self.code = safe_code
        super().__init__(safe_code)


class AuthVerifier(Protocol):
    """Port for converting transient proof into verified receipt evidence."""

    def verify(self, request: AuthenticationRequest) -> AuthReceiptV1:
        """Return a verified credential-free receipt or raise a safe denial."""


class AuthorityContextFactory:
    """Construct authority only from verifier-issued receipt contracts."""

    def root(self, receipt: AuthReceiptV1) -> AuthorityContextV1:
        """Build requester-equals-actor root authority without delegation."""

        if not isinstance(receipt, AuthReceiptV1):
            raise AuthenticationDenied("authentication_rejected")
        if receipt.authentication != "authenticated" or receipt.principal is None:
            raise AuthenticationDenied("authentication_rejected")

        party = VerifiedPartyV1(principal=receipt.principal, auth_receipt=receipt)
        return AuthorityContextV1(requester=party, actor=party, delegation=None)
