"""Validation boundary for credential-free Authstructure receipt artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit

from .contracts import AuthReceiptV1
from .verifier import AuthenticationDenied, AuthenticationRequest

AUTHSTRUCTURE_RECEIPT_FORMAT = "authstructure.receipt/2"
# Exact whole-name aliases are compared after removing ASCII separators and
# case. This makes snake, kebab, camel, and acronym spellings equivalent while
# keeping identifier metadata such as ``token-key-id`` outside the grammar.
_SENSITIVE_PROOF_NAMES = frozenset(
    {
        "accesskey",
        "accesstoken",
        "apikey",
        "apisecret",
        "apitoken",
        "authorization",
        "authorizationcode",
        "authtoken",
        "awssecretaccesskey",
        "bearertoken",
        "certificate",
        "certificatepem",
        "clientcertificate",
        "clientcredentials",
        "clientproof",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "dpop",
        "githubtoken",
        "hftoken",
        "idtoken",
        "jwt",
        "neonapikey",
        "openaiapikey",
        "anthropicapikey",
        "passphrase",
        "password",
        "privatekey",
        "providerapikey",
        "providerapitoken",
        "providersecret",
        "providertoken",
        "proof",
        "proxyauthorization",
        "refreshtoken",
        "requestproof",
        "requestsignature",
        "secret",
        "secretkey",
        "sessiontoken",
        "setcookie",
        "signature",
        "stripesecretkey",
        "token",
        "xaccesstoken",
        "xapikey",
        "xapisecret",
        "xapitoken",
        "xauthtoken",
        "xbearertoken",
        "xclientproof",
        "xrefreshtoken",
        "xrequestsignature",
        "xsessiontoken",
    }
)
_AUTHORIZATION_PROOF_NAMES = frozenset({"authorization", "proxyauthorization"})
_COOKIE_PROOF_NAME = "cookie"
_SET_COOKIE_PROOF_NAME = "setcookie"
# Every nonempty value under an exact sensitive alias is proof. Exact receipt
# leaf matches always deny; sufficiently high-information values also deny when
# contained in a larger receipt leaf, such as a prefixed Authorization echo.
_PROOF_CONTAINMENT_MIN_LENGTH = 16


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

        artifact: object = None
        boundary_denial: AuthenticationDenied | None = None
        try:
            artifact = self._boundary.verify(request)
        # A boundary may fail with any adapter exception. The fail-closed
        # translation deliberately discards its potentially secret message.
        except Exception:  # noqa: BLE001
            boundary_denial = AuthenticationDenied("auth_verifier_unavailable")
        if boundary_denial is not None:
            raise boundary_denial

        receipt: AuthReceiptV1 | None = None
        processing_denial: AuthenticationDenied | None = None
        try:
            receipt = self._validate_artifact(artifact, request)
        except AuthenticationDenied as denied:
            processing_denial = AuthenticationDenied(denied.code)
        # Receipt artifacts are untrusted adapter output. Any unexpected
        # normalization or admission error must become a safe denial.
        except Exception:  # noqa: BLE001
            processing_denial = AuthenticationDenied("authentication_rejected")
        if processing_denial is not None:
            raise processing_denial
        if receipt is None:
            raise AuthenticationDenied("authentication_rejected")
        return receipt

    def _validate_artifact(
        self,
        artifact: object,
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
        if self._contains_structured_proof_echo(
            receipt.model_dump(mode="json", warnings="error"),
            request,
        ):
            raise AuthenticationDenied("authentication_rejected")
        return receipt

    def _safe_now(self) -> datetime:
        now: datetime | None = None
        clock_denial: AuthenticationDenied | None = None
        try:
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            return now
        # Clock failures are admission failures; their details are not safe
        # authentication output and must not escape this boundary.
        except Exception:  # noqa: BLE001
            clock_denial = AuthenticationDenied("receipt_time_invalid")
        if clock_denial is not None:
            raise clock_denial
        if now is None:
            raise AuthenticationDenied("receipt_time_invalid")
        return now

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
    def _contains_structured_proof_echo(
        cls,
        receipt_dump: Mapping[str, object],
        request: AuthenticationRequest,
    ) -> bool:
        proof_leaves = cls._structured_proof_leaves(request)
        if not proof_leaves:
            return False
        return any(
            receipt_leaf == proof_leaf
            or (
                len(proof_leaf) >= _PROOF_CONTAINMENT_MIN_LENGTH
                and proof_leaf in receipt_leaf
            )
            for receipt_leaf in cls._string_leaves(receipt_dump)
            for proof_leaf in proof_leaves
        )

    @classmethod
    def _string_leaves(cls, value: object) -> Sequence[str]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Mapping):
            return tuple(
                leaf for nested in value.values() for leaf in cls._string_leaves(nested)
            )
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(leaf for item in value for leaf in cls._string_leaves(item))
        return ()

    @classmethod
    def _structured_proof_leaves(cls, request: AuthenticationRequest) -> frozenset[str]:
        leaves: set[str] = set()
        for name, values in request.headers.items():
            normalized_name = cls._normalize_proof_name(name)
            if normalized_name not in _SENSITIVE_PROOF_NAMES:
                continue
            for value in values:
                if not value:
                    continue
                leaves.add(value)
                if normalized_name in _AUTHORIZATION_PROOF_NAMES:
                    payload = cls._authorization_payload(value)
                    if payload:
                        leaves.add(payload)
                elif normalized_name == _COOKIE_PROOF_NAME:
                    leaves.update(cls._cookie_values(value, first_only=False))
                elif normalized_name == _SET_COOKIE_PROOF_NAME:
                    leaves.update(cls._cookie_values(value, first_only=True))

        try:
            body_text = request.body.decode("utf-8")
            body_value = json.loads(
                body_text,
                object_pairs_hook=lambda pairs: tuple(pairs),
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        else:
            body_leaves = cls._named_structured_proof_leaves(body_value)
            leaves.update(body_leaves)
            if body_leaves:
                leaves.add(body_text)

        try:
            raw_target = request.raw_target.decode("utf-8")
            query_pairs = parse_qsl(
                urlsplit(raw_target).query,
                keep_blank_values=True,
                strict_parsing=False,
            )
        except (UnicodeDecodeError, ValueError):
            pass
        else:
            target_leaves = {
                value
                for name, value in query_pairs
                if cls._is_sensitive_proof_name(name) and value
            }
            leaves.update(target_leaves)
            if target_leaves:
                leaves.add(raw_target)
        return frozenset(leaves)

    @classmethod
    def _named_structured_proof_leaves(cls, value: object) -> frozenset[str]:
        leaves: set[str] = set()
        if isinstance(value, tuple):
            for name, nested in value:
                if cls._is_sensitive_proof_name(name):
                    leaves.update(
                        leaf for leaf in cls._parsed_json_string_leaves(nested) if leaf
                    )
                else:
                    leaves.update(cls._named_structured_proof_leaves(nested))
        elif isinstance(value, list):
            for nested in value:
                leaves.update(cls._named_structured_proof_leaves(nested))
        return frozenset(leaves)

    @classmethod
    def _parsed_json_string_leaves(cls, value: object) -> Sequence[str]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, tuple):
            return tuple(
                leaf
                for _name, nested in value
                for leaf in cls._parsed_json_string_leaves(nested)
            )
        if isinstance(value, list):
            return tuple(
                leaf
                for nested in value
                for leaf in cls._parsed_json_string_leaves(nested)
            )
        return ()

    @staticmethod
    def _authorization_payload(value: str) -> str | None:
        parts = value.split(None, 1)
        if len(parts) != 2:
            return None
        payload = parts[1].strip()
        return payload or None

    @staticmethod
    def _cookie_values(value: str, *, first_only: bool) -> frozenset[str]:
        leaves: set[str] = set()
        segments = AuthstructureVerifier._cookie_segments(value)
        if first_only:
            segments = segments[:1]
        for segment in segments:
            if "=" not in segment:
                continue
            _name, raw_cookie_value = segment.split("=", 1)
            cookie_value = raw_cookie_value.strip()
            if cookie_value:
                leaves.add(cookie_value)
            if cookie_value.startswith(('"', "'")):
                quote = cookie_value[0]
                inner = (
                    cookie_value[1:-1]
                    if cookie_value.endswith(quote) and len(cookie_value) >= 2
                    else cookie_value[1:]
                )
                if inner:
                    leaves.add(inner)
                    leaves.add(re.sub(r"\\(.)", r"\1", inner))
        return frozenset(leaves)

    @staticmethod
    def _cookie_segments(value: str) -> tuple[str, ...]:
        segments: list[str] = []
        start = 0
        quote: str | None = None
        escaped = False
        for index, character in enumerate(value):
            if escaped:
                escaped = False
                continue
            if character == "\\" and quote is not None:
                escaped = True
                continue
            if character in {'"', "'"}:
                if quote is None:
                    quote = character
                elif quote == character:
                    quote = None
                continue
            if character == ";" and quote is None:
                segments.append(value[start:index])
                start = index + 1
        segments.append(value[start:])
        return tuple(segments)

    @staticmethod
    def _is_sensitive_proof_name(name: str) -> bool:
        return (
            AuthstructureVerifier._normalize_proof_name(name) in _SENSITIVE_PROOF_NAMES
        )

    @staticmethod
    def _normalize_proof_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.casefold())
