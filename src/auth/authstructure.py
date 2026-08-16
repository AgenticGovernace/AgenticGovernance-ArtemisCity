"""Validation boundary for credential-free Authstructure receipt artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .contracts import AuthReceiptV1
from .verifier import AuthenticationDenied, AuthenticationRequest

AUTHSTRUCTURE_RECEIPT_FORMAT = "authstructure.receipt/2"


@dataclass(frozen=True)
class AuthstructureReceiptArtifact:
    """Credential-free receipt plus the canonical bytes covered by its digest."""

    receipt: AuthReceiptV1
    canonical_receipt_bytes: bytes


class AuthstructureValidationBoundary(Protocol):
    """Injected adapter for the future public Authstructure verifier contract."""

    def verify(self, request: AuthenticationRequest) -> AuthstructureReceiptArtifact:
        """Validate transient proof and return a credential-free receipt artifact."""


class AuthstructureVerifier:
    """Apply Artemis admission checks to an Authstructure verification artifact."""

    def __init__(
        self,
        *,
        boundary: AuthstructureValidationBoundary,
        expected_audience: str,
        expected_signer_namespace: str,
        expected_receipt_key_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._boundary = boundary
        self._expected_audience = expected_audience
        self._expected_signer_namespace = expected_signer_namespace
        self._expected_receipt_key_id = expected_receipt_key_id
        self._clock = clock

    def verify(self, request: AuthenticationRequest) -> AuthReceiptV1:
        """Return a validated receipt or raise a stable credential-free denial."""

        try:
            artifact = self._boundary.verify(request)
        # A boundary may fail with any adapter exception. The fail-closed
        # translation deliberately discards its potentially secret message.
        except Exception:  # noqa: BLE001
            raise AuthenticationDenied("auth_verifier_unavailable") from None

        if not isinstance(artifact, AuthstructureReceiptArtifact):
            raise AuthenticationDenied("authentication_rejected")

        receipt = artifact.receipt
        if not isinstance(receipt, AuthReceiptV1):
            raise AuthenticationDenied("authentication_rejected")
        if receipt.authentication != "authenticated" or receipt.principal is None:
            raise AuthenticationDenied("authentication_rejected")
        if receipt.source.format != AUTHSTRUCTURE_RECEIPT_FORMAT:
            raise AuthenticationDenied("unsupported_receipt_version")
        if (
            receipt.source.signer_namespace != self._expected_signer_namespace
            or receipt.source.receipt_key_id != self._expected_receipt_key_id
        ):
            raise AuthenticationDenied("invalid_signature_metadata")

        expected_bytes = self._canonical_receipt_bytes(receipt)
        if not isinstance(
            artifact.canonical_receipt_bytes, bytes
        ) or not hmac.compare_digest(artifact.canonical_receipt_bytes, expected_bytes):
            raise AuthenticationDenied("receipt_canonicalization_mismatch")

        expected_hash = f"sha256:{hashlib.sha256(expected_bytes).hexdigest()}"
        if not hmac.compare_digest(receipt.source.record_hash, expected_hash):
            raise AuthenticationDenied("receipt_hash_mismatch")
        if receipt.request_id != request.request_id:
            raise AuthenticationDenied("receipt_request_mismatch")
        if receipt.principal.capability.audience != self._expected_audience:
            raise AuthenticationDenied("receipt_audience_mismatch")

        now = self._safe_now()
        if (
            receipt.verified_at > now
            or receipt.principal.verified_at > receipt.verified_at
        ):
            raise AuthenticationDenied("receipt_time_invalid")
        if receipt.principal.expires_at <= now:
            raise AuthenticationDenied("principal_expired")
        return receipt

    def _safe_now(self) -> datetime:
        try:
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            return now
        # Clock failures are admission failures; their details are not safe
        # authentication output and must not escape this boundary.
        except Exception:  # noqa: BLE001
            raise AuthenticationDenied("receipt_time_invalid") from None

    @staticmethod
    def _canonical_receipt_bytes(receipt: AuthReceiptV1) -> bytes:
        source = receipt.source.model_dump(mode="json")
        return json.dumps(
            source["canonical_receipt"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
