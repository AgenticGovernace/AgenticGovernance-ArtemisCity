"""Validation boundary for credential-free Authstructure receipt artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .contracts import AuthReceiptV1
from .verifier import AuthenticationDenied, AuthenticationRequest

AUTHSTRUCTURE_RECEIPT_FORMAT = "authstructure.receipt/2"


@dataclass(frozen=True, repr=False)
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

        try:
            return self._validate_artifact(artifact, request)
        except AuthenticationDenied as denied:
            raise AuthenticationDenied(denied.code) from None
        # Receipt artifacts are untrusted adapter output. Any unexpected
        # normalization or admission error must become a safe denial.
        except Exception:  # noqa: BLE001
            raise AuthenticationDenied("authentication_rejected") from None

    def _validate_artifact(
        self,
        artifact: AuthstructureReceiptArtifact,
        request: AuthenticationRequest,
    ) -> AuthReceiptV1:
        if not isinstance(artifact, AuthstructureReceiptArtifact):
            raise AuthenticationDenied("authentication_rejected")
        if not isinstance(artifact.canonical_receipt_bytes, bytes):
            raise AuthenticationDenied("receipt_canonicalization_mismatch")
        if not isinstance(artifact.receipt, AuthReceiptV1):
            raise AuthenticationDenied("authentication_rejected")

        dumped_receipt = artifact.receipt.model_dump(mode="python", warnings="error")
        receipt = AuthReceiptV1.model_validate(dumped_receipt)
        if receipt.authentication != "authenticated" or receipt.principal is None:
            raise AuthenticationDenied("authentication_rejected")

        canonical_bytes = bytes(artifact.canonical_receipt_bytes)
        parsed_projection = self._parse_strict_json_object(canonical_bytes)
        expected_projection = self._signed_projection(receipt)
        expected_bytes = self._canonical_json_bytes(expected_projection)
        source_dump = receipt.source.model_dump(mode="json", warnings="error")
        if (
            parsed_projection != expected_projection
            or source_dump["canonical_receipt"] != expected_projection
            or not hmac.compare_digest(canonical_bytes, expected_bytes)
        ):
            raise AuthenticationDenied("receipt_canonicalization_mismatch")

        expected_hash = f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"
        if not hmac.compare_digest(receipt.source.record_hash, expected_hash):
            raise AuthenticationDenied("receipt_hash_mismatch")
        if receipt.source.format != AUTHSTRUCTURE_RECEIPT_FORMAT:
            raise AuthenticationDenied("unsupported_receipt_version")
        if (
            receipt.source.signer_namespace != self._expected_signer_namespace
            or receipt.source.receipt_key_id != self._expected_receipt_key_id
        ):
            raise AuthenticationDenied("invalid_signature_metadata")
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
        if self._contains_raw_proof(
            receipt.model_dump(mode="json", warnings="error"),
            canonical_bytes,
            request,
        ):
            raise AuthenticationDenied("authentication_rejected")
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

    @classmethod
    def _signed_projection(cls, receipt: AuthReceiptV1) -> dict[str, object]:
        principal = receipt.principal
        if principal is None:
            principal_projection = None
        else:
            principal_projection = {
                "version": principal.version,
                "identity": principal.identity.model_dump(mode="json"),
                "capability": {
                    "token_issuer": principal.capability.token_issuer,
                    "audience": principal.capability.audience,
                    "token_key_id": principal.capability.token_key_id,
                    "token_jti_ref": principal.capability.token_jti_ref,
                    "granted_scopes": sorted(principal.capability.granted_scopes),
                },
                "verified_at": principal.verified_at.isoformat(),
                "expires_at": principal.expires_at.isoformat(),
            }
        return {
            "version": receipt.version,
            "request_id": receipt.request_id,
            "authentication": receipt.authentication,
            "principal": principal_projection,
            "reason_code": receipt.reason_code,
            "verified_at": receipt.verified_at.isoformat(),
            "source": {
                "format": receipt.source.format,
                "receipt_id": receipt.source.receipt_id,
                "receipt_key_id": receipt.source.receipt_key_id,
                "signer_namespace": receipt.source.signer_namespace,
            },
        }

    @staticmethod
    def _canonical_json_bytes(projection: Mapping[str, object]) -> bytes:
        return json.dumps(
            projection,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _parse_strict_json_object(canonical_bytes: bytes) -> dict[str, object]:
        def reject_duplicate_keys(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        def reject_constant(value: str) -> None:
            del value
            raise ValueError

        parsed = json.loads(
            canonical_bytes.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
        if not isinstance(parsed, dict):
            raise TypeError
        return parsed

    @classmethod
    def _contains_raw_proof(
        cls,
        receipt_dump: Mapping[str, object],
        canonical_bytes: bytes,
        request: AuthenticationRequest,
    ) -> bool:
        byte_fragments = [request.body, request.raw_target]
        text_fragments: list[str] = []
        for values in request.headers.values():
            for value in values:
                text_fragments.append(value)
                byte_fragments.append(value.encode("utf-8"))
        for fragment in (request.body, request.raw_target):
            try:
                text_fragments.append(fragment.decode("utf-8"))
            except UnicodeDecodeError:
                pass

        byte_fragments = [fragment for fragment in byte_fragments if fragment]
        text_fragments = [fragment for fragment in text_fragments if fragment]
        if any(fragment in canonical_bytes for fragment in byte_fragments):
            return True
        return cls._value_contains_fragment(receipt_dump, text_fragments)

    @classmethod
    def _value_contains_fragment(cls, value: object, fragments: Sequence[str]) -> bool:
        if isinstance(value, str):
            return any(fragment in value for fragment in fragments)
        if isinstance(value, Mapping):
            return any(
                cls._value_contains_fragment(key, fragments)
                or cls._value_contains_fragment(nested, fragments)
                for key, nested in value.items()
            )
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return any(cls._value_contains_fragment(item, fragments) for item in value)
        return False
