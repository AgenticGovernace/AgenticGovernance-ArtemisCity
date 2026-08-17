"""Strict, credential-free contracts for verified authentication evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal, NoReturn

from pydantic import (BaseModel, ConfigDict, Field, field_serializer,
                      field_validator, model_validator)
from pydantic_core import PydanticCustomError

_FORBIDDEN_CREDENTIAL_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization_code",
        "bearer_token",
        "certificate",
        "certificate_pem",
        "client_secret",
        "password",
        "private_key",
        "provider_secret",
        "refresh_token",
        "secret",
        "token",
    }
)
_NORMALIZED_FORBIDDEN_CREDENTIAL_FIELDS = frozenset(
    "".join(character for character in field if character.isalnum())
    for field in _FORBIDDEN_CREDENTIAL_FIELDS
)
_REJECTED_REASON_CODES = frozenset(
    {
        "authentication_rejected",
        "expired_request_proof",
        "invalid_request_proof",
        "invalid_transport",
        "untrusted_issuer",
    }
)


class FrozenJsonDict(Mapping[str, object]):
    """A read-only JSON object used for signed receipt projections."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise TypeError("canonical receipt projection is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable


def _freeze_json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("canonical_receipt must contain only JSON-safe values")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise PydanticCustomError(
                    "json_safe_value",
                    "canonical_receipt must contain only JSON-safe values",
                )
            frozen[key] = _freeze_json_value(nested_value)
        return FrozenJsonDict(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise ValueError("canonical_receipt must contain only JSON-safe values")


def _freeze_json_object(value: object) -> FrozenJsonDict:
    frozen = _freeze_json_value(value)
    if not isinstance(frozen, FrozenJsonDict):
        raise PydanticCustomError(
            "json_object", "canonical_receipt must be a JSON object"
        )
    return frozen


def _thaw_json_value(value: object) -> object:
    if isinstance(value, FrozenJsonDict):
        return {key: _thaw_json_value(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


def _forbidden_credential_field(value: object) -> str | None:
    """Return the first recursively found credential field name, if present."""

    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            normalized_key = "".join(
                character for character in str(key).lower() if character.isalnum()
            )
            if normalized_key in _NORMALIZED_FORBIDDEN_CREDENTIAL_FIELDS:
                return str(key)
            forbidden = _forbidden_credential_field(nested_value)
            if forbidden is not None:
                return forbidden
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested_value in value:
            forbidden = _forbidden_credential_field(nested_value)
            if forbidden is not None:
                return forbidden
    elif isinstance(value, BaseModel):
        return _forbidden_credential_field(value.model_dump())
    return None


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


class AuthorityModel(BaseModel):
    """Strict immutable base for credential-free authority records."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="before")
    @classmethod
    def reject_credential_material(cls, value: Any) -> Any:
        forbidden = _forbidden_credential_field(value)
        if forbidden is not None:
            raise ValueError(f"credential material is forbidden: {forbidden}")
        return value


class PrincipalIdentityV1(AuthorityModel):
    """Verified non-secret identity references for one Artemis principal."""

    actor_issuer: str = Field(min_length=1)
    actor_subject_ref: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    certificate_issuer: str = Field(min_length=1)
    certificate_serial: str = Field(min_length=1)
    certificate_thumbprint: str = Field(min_length=1)
    request_key_id: str = Field(min_length=1)
    request_key_jkt: str = Field(min_length=1)


class PrincipalCapabilityV1(AuthorityModel):
    """Verified issuer evidence and the scopes granted to a principal."""

    token_issuer: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    token_key_id: str = Field(min_length=1)
    token_jti_ref: str = Field(min_length=1)
    granted_scopes: frozenset[str]

    @field_validator("granted_scopes")
    @classmethod
    def normalize_scopes(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip() for value in values if value.strip())
        if not normalized:
            raise ValueError("granted_scopes must contain verified evidence")
        return normalized


class PrincipalV1(AuthorityModel):
    """Versioned identity and capability evidence with a bounded lifetime."""

    version: Literal["artemis.principal/1"] = "artemis.principal/1"
    identity: PrincipalIdentityV1
    capability: PrincipalCapabilityV1
    verified_at: datetime
    expires_at: datetime

    _aware_verified_at = field_validator("verified_at")(_require_aware)
    _aware_expires_at = field_validator("expires_at")(_require_aware)

    @model_validator(mode="after")
    def require_unexpired_capability_evidence(self) -> PrincipalV1:
        if self.expires_at <= self.verified_at:
            raise ValueError("expires_at must be later than verified_at")
        return self


class AuthReceiptSourceV1(AuthorityModel):
    """Immutable provenance metadata for a signed authentication receipt."""

    format: str = Field(min_length=1)
    receipt_id: str = Field(min_length=1)
    record_hash: str = Field(min_length=1)
    receipt_key_id: str = Field(min_length=1)
    signer_namespace: str = Field(min_length=1)
    canonical_receipt: FrozenJsonDict

    @field_validator("canonical_receipt", mode="before")
    @classmethod
    def freeze_canonical_receipt(cls, value: object) -> FrozenJsonDict:
        return _freeze_json_object(value)

    @field_serializer("canonical_receipt")
    def serialize_canonical_receipt(self, value: FrozenJsonDict) -> dict[str, object]:
        serialized = _thaw_json_value(value)
        assert isinstance(
            serialized, dict
        )  # thawing a FrozenJsonDict always yields a dict  # nosec B101
        return serialized


class AuthReceiptV1(AuthorityModel):
    """Credential-free authentication outcome consumed by Artemis."""

    version: Literal["artemis.auth-receipt/1"] = "artemis.auth-receipt/1"
    request_id: str = Field(min_length=1)
    authentication: Literal["authenticated", "rejected"]
    principal: PrincipalV1 | None
    reason_code: str | None
    verified_at: datetime
    source: AuthReceiptSourceV1

    _aware_verified_at = field_validator("verified_at")(_require_aware)

    @model_validator(mode="after")
    def require_consistent_authentication_state(self) -> AuthReceiptV1:
        if self.authentication == "authenticated":
            if self.principal is None:
                raise ValueError("authenticated receipt requires a principal")
            if self.reason_code is not None:
                raise ValueError("authenticated receipt requires a null reason_code")
            if self.verified_at >= self.principal.expires_at:
                raise ValueError("expires_at must be later than receipt verification")
        else:
            if self.principal is not None:
                raise ValueError("rejected receipt cannot carry a principal")
            if self.reason_code not in _REJECTED_REASON_CODES:
                raise ValueError("rejected receipt requires a registered reason_code")
        return self


class VerifiedPartyV1(AuthorityModel):
    """A principal paired with the authenticated receipt that proves it."""

    principal: PrincipalV1
    auth_receipt: AuthReceiptV1

    @model_validator(mode="after")
    def require_matching_authenticated_receipt(self) -> VerifiedPartyV1:
        if self.auth_receipt.authentication != "authenticated":
            raise ValueError("party requires an authenticated receipt")
        if self.auth_receipt.principal != self.principal:
            raise ValueError("party principal must match the receipt principal")
        return self


class DelegationReferenceV1(AuthorityModel):
    """Optional identifier and digest for one persisted delegation grant."""

    grant_id: str | None
    grant_hash: str | None

    @model_validator(mode="after")
    def require_paired_reference(self) -> DelegationReferenceV1:
        if (self.grant_id is None) != (self.grant_hash is None):
            raise ValueError("grant_id and grant_hash must be provided together")
        return self


class AuthorityContextV1(AuthorityModel):
    """Requester, acting party, and optional bounded delegation evidence."""

    requester: VerifiedPartyV1
    actor: VerifiedPartyV1
    delegation: DelegationReferenceV1 | None
