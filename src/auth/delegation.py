"""Immutable delegation-grant contracts and lookup port."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from .contracts import AuthorityModel, _require_aware


def _canonical_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: _canonical_value(nested) for key, nested in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical_value(item) for item in value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


class DelegationGrantV1(AuthorityModel):
    """An immutable, non-bearer ledger record for bounded child authority."""

    version: Literal["artemis.delegation-grant/1"] = "artemis.delegation-grant/1"
    grant_id: str = Field(min_length=1)
    grant_hash: str = Field(min_length=1)
    root_task_id: str = Field(min_length=1)
    parent_task_id: str = Field(min_length=1)
    parent_outcome_id: str = Field(min_length=1)
    requester_principal_ref: str = Field(min_length=1)
    requester_auth_receipt_id: str = Field(min_length=1)
    requester_auth_receipt_hash: str = Field(min_length=1)
    actor_principal_ref: str = Field(min_length=1)
    actor_auth_receipt_id: str = Field(min_length=1)
    actor_auth_receipt_hash: str = Field(min_length=1)
    allowed_modes: frozenset[str]
    allowed_action_types: frozenset[str]
    allowed_capabilities: frozenset[str]
    allowed_target_zones: frozenset[str]
    depth_limit: int = Field(ge=0)
    budget_reservation_id: str = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime
    policy_version: str = Field(min_length=1)

    _aware_issued_at = field_validator("issued_at")(_require_aware)
    _aware_expires_at = field_validator("expires_at")(_require_aware)

    @field_validator(
        "allowed_modes",
        "allowed_action_types",
        "allowed_capabilities",
        "allowed_target_zones",
    )
    @classmethod
    def require_nonempty_allowlist(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip() for value in values if value.strip())
        if not normalized:
            raise ValueError("delegation allowlists must contain at least one value")
        return normalized

    @model_validator(mode="after")
    def verify_ledger_record(self) -> DelegationGrantV1:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")
        if self.grant_hash != self.canonical_hash():
            raise ValueError("grant_hash does not match canonical grant bytes")
        return self

    def canonical_hash(self) -> str:
        """Return the SHA-256 hash of canonical bytes without ``grant_hash``."""

        payload = self.model_dump(exclude={"grant_hash"})
        canonical = json.dumps(
            _canonical_value(payload), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(canonical).hexdigest()


class DelegationGrantLookup(Protocol):
    """Port for loading immutable persisted delegation grants by identifier."""

    def get(self, grant_id: str) -> DelegationGrantV1 | None:
        """Return a grant by id, or ``None`` when it is not present."""
