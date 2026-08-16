"""Strict immutable contracts for Artemis Routing Kernel boundaries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.auth.contracts import AuthorityContextV1

TaskState = Literal[
    "pending",
    "running",
    "finalizing",
    "completed",
    "failed",
    "retry_wait",
    "waiting_children",
    "blocked",
    "cancelled",
]
OutcomeStatus = Literal["success", "failed", "blocked", "cancelled"]
OutcomeClassification = Literal[
    "success",
    "agent_failure",
    "provider_failure",
    "degraded_success",
    "governance_denial",
    "invalid_agent_result",
    "graph_control",
]
KernelEventType = Literal[
    "accepted",
    "routing",
    "token",
    "finalizing",
    "complete",
    "error",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BEARER_CREDENTIAL_RE = re.compile(
    r"\bBearer[ \t]+[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}" r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----", re.IGNORECASE
)
_CONTROL_RESULT_KINDS = frozenset({"planning", "checkpoint", "graph_control"})
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


def _require_aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


def _require_sha256(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError("must be a lowercase 64-hex SHA-256 digest")
    return value


def _credential_violation(value: object) -> str | None:
    """Return a safe description of recursively detected credential material."""

    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            normalized_key = "".join(
                character for character in str(key).lower() if character.isalnum()
            )
            if normalized_key in _NORMALIZED_FORBIDDEN_CREDENTIAL_FIELDS:
                return str(key)
            nested_violation = _credential_violation(nested_value)
            if nested_violation is not None:
                return nested_violation
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested_value in value:
            nested_violation = _credential_violation(nested_value)
            if nested_violation is not None:
                return nested_violation
    elif isinstance(value, BaseModel):
        return _credential_violation(value.model_dump())
    elif isinstance(value, str):
        if _BEARER_CREDENTIAL_RE.search(value):
            return "raw Bearer credential"
        if _PRIVATE_KEY_RE.search(value):
            return "private key material"
    return None


class RoutingModel(BaseModel):
    """Shared strict, immutable base for routing-contract records."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True
    )

    @model_validator(mode="before")
    @classmethod
    def reject_credential_material(cls, value: Any) -> Any:
        violation = _credential_violation(value)
        if violation is not None:
            raise ValueError(f"credential material is forbidden: {violation}")
        return value


class TaskIntentV1(RoutingModel):
    """Intent supplied by strict ATP parsing or a trusted typed adapter."""

    mode: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    context: str = Field(min_length=1)
    target_zone: str = Field(min_length=1)
    source: Literal["caller-atp", "typed-adapter"]


class RequestedConstraintsV1(RoutingModel):
    """Caller-requested routing constraints, which may only later narrow policy."""

    capability: str | None = Field(default=None, min_length=1)
    agent: str | None = Field(default=None, min_length=1)


class DelegationContextV1(RoutingModel):
    """Safe references linking a root or child envelope to ledger delegation."""

    grant_id: str | None = Field(default=None, min_length=1)
    grant_hash: str | None = Field(default=None, min_length=1)
    root_task_id: str = Field(min_length=1)
    parent_task_id: str | None = Field(default=None, min_length=1)
    parent_outcome_id: str | None = Field(default=None, min_length=1)
    depth: int = Field(ge=0)

    @field_validator("grant_hash")
    @classmethod
    def validate_grant_hash(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_sha256(value)
        return value

    @model_validator(mode="after")
    def require_consistent_delegation(self) -> DelegationContextV1:
        if (self.grant_id is None) != (self.grant_hash is None):
            raise ValueError("grant_id and grant_hash must be provided together")
        parent_references = (self.parent_task_id, self.parent_outcome_id)
        if (parent_references[0] is None) != (parent_references[1] is None):
            raise ValueError(
                "parent_task_id and parent_outcome_id must be provided together"
            )
        if self.parent_task_id is None:
            if self.depth != 0 or self.grant_id is not None:
                raise ValueError("root delegation must have depth zero and no grant")
        elif self.depth == 0 or self.grant_id is None:
            raise ValueError("child delegation requires a grant and positive depth")
        return self


class ContinuationV1(RoutingModel):
    """The deterministic result-set identity for an execution continuation."""

    sequence: int = Field(ge=0)
    child_result_set_sha256: str | None = None
    prior_outcome_id: str | None = Field(default=None, min_length=1)

    @field_validator("child_result_set_sha256")
    @classmethod
    def validate_child_result_set_sha256(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_sha256(value)
        return value

    @model_validator(mode="after")
    def require_consistent_sequence(self) -> ContinuationV1:
        if self.sequence == 0:
            if (
                self.child_result_set_sha256 is not None
                or self.prior_outcome_id is not None
            ):
                raise ValueError("root continuation must not link child results")
        elif self.child_result_set_sha256 is None or self.prior_outcome_id is None:
            raise ValueError(
                "root continuation must use sequence zero; a child continuation "
                "requires linked child results and prior outcome"
            )
        return self


class TaskSubmissionV1(RoutingModel):
    """Caller transport shape, deliberately excluding trusted authority values."""

    version: Literal["artemis.task-submission/1"] = "artemis.task-submission/1"
    task_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    input_sha256: str
    ingress: str = Field(min_length=1)
    content: str = Field(min_length=1)
    intent: TaskIntentV1
    requested_constraints: RequestedConstraintsV1
    provenance_parent_id: str | None = Field(default=None, min_length=1)
    submission_idempotency_key: str = Field(min_length=1)
    attempt_idempotency_key: str = Field(min_length=1)
    created_at: datetime

    _valid_input_sha256 = field_validator("input_sha256")(_require_sha256)
    _aware_created_at = field_validator("created_at")(_require_aware_timestamp)

    @model_validator(mode="after")
    def require_caller_atp_source(self) -> TaskSubmissionV1:
        if self.intent.source != "caller-atp":
            raise ValueError(
                "caller submissions cannot use typed-adapter intent source"
            )
        return self


class TaskEnvelopeV1(RoutingModel):
    """Trusted in-process task envelope accepted by the Routing Kernel."""

    version: Literal["artemis.task/1"] = "artemis.task/1"
    task_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    input_sha256: str
    ingress: str = Field(min_length=1)
    authority: AuthorityContextV1
    content: str = Field(min_length=1)
    intent: TaskIntentV1
    requested_constraints: RequestedConstraintsV1
    delegation: DelegationContextV1
    continuation: ContinuationV1
    provenance_parent_id: str | None = Field(default=None, min_length=1)
    submission_idempotency_key: str = Field(min_length=1)
    attempt_idempotency_key: str = Field(min_length=1)
    created_at: datetime

    _valid_input_sha256 = field_validator("input_sha256")(_require_sha256)
    _aware_created_at = field_validator("created_at")(_require_aware_timestamp)

    @model_validator(mode="after")
    def require_root_or_child_consistency(self) -> TaskEnvelopeV1:
        is_root = self.delegation.parent_task_id is None
        if self.delegation.root_task_id != self.task_id and is_root:
            raise ValueError("root delegation must reference the envelope task_id")
        if is_root and self.continuation.sequence != 0:
            raise ValueError("root continuation requires sequence zero")
        if not is_root and self.continuation.sequence == 0:
            raise ValueError("child envelope requires a non-root continuation")
        return self


class ResolvedIntentV1(RoutingModel):
    """The resolved authorized capability derived from a submitted intent."""

    mode: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    context: str = Field(min_length=1)
    target_zone: str = Field(min_length=1)
    source: Literal["caller-atp", "typed-adapter"]
    capability: str = Field(min_length=1)


class AuthorizedRouteRequestV1(RoutingModel):
    """The authority-bearing request passed from authorization to routing."""

    envelope: TaskEnvelopeV1
    resolved_intent: ResolvedIntentV1
    authority: AuthorityContextV1

    @model_validator(mode="after")
    def require_envelope_authority(self) -> AuthorizedRouteRequestV1:
        if self.authority != self.envelope.authority:
            raise ValueError("authority must match the trusted envelope authority")
        intent_fields = ("mode", "action_type", "context", "target_zone", "source")
        if any(
            getattr(self.resolved_intent, field) != getattr(self.envelope.intent, field)
            for field in intent_fields
        ):
            raise ValueError("resolved intent must match the envelope intent")
        requested_capability = self.envelope.requested_constraints.capability
        if (
            requested_capability is not None
            and requested_capability != self.resolved_intent.capability
        ):
            raise ValueError("requested capability must match the resolved capability")
        return self


class RoutingDecisionV1(RoutingModel):
    """Durable, explainable output from the governed routing decision."""

    version: Literal["artemis.routing-decision/1"] = "artemis.routing-decision/1"
    decision_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    continuation_sequence: int = Field(ge=0)
    resolved_capability: str = Field(min_length=1)
    selected_agent_id: str | None = Field(default=None, min_length=1)
    fallback_used: bool
    reason_code: str = Field(min_length=1)
    provenance_id: str = Field(min_length=1)


class OutcomeV1(RoutingModel):
    """Canonical durable result used for state transition and learning policy."""

    version: Literal["artemis.outcome/1"] = "artemis.outcome/1"
    outcome_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    continuation_sequence: int = Field(ge=0)
    child_result_set_sha256: str | None = None
    prior_outcome_id: str | None = Field(default=None, min_length=1)
    status: OutcomeStatus
    classification: OutcomeClassification
    result_kind: Literal["terminal", "planning", "checkpoint", "graph_control"] = (
        "terminal"
    )
    retryable: bool
    content_sha256: str
    artifact_sha256: str | None = None
    agent_id: str | None = Field(default=None, min_length=1)
    routing_decision: RoutingDecisionV1
    requester_principal_ref: str = Field(min_length=1)
    requester_auth_receipt_id: str = Field(min_length=1)
    requester_auth_receipt_hash: str
    actor_principal_ref: str = Field(min_length=1)
    actor_auth_receipt_id: str = Field(min_length=1)
    actor_auth_receipt_hash: str
    delegation_grant_id: str | None = Field(default=None, min_length=1)
    delegation_grant_hash: str | None = Field(default=None, min_length=1)
    provenance_parent_id: str | None = Field(default=None, min_length=1)
    result_provenance_id: str = Field(min_length=1)
    created_at: datetime
    learning_eligible: bool

    _valid_child_result_set_sha256 = field_validator("child_result_set_sha256")(
        lambda value: _require_sha256(value) if value is not None else value
    )
    _valid_content_sha256 = field_validator("content_sha256")(_require_sha256)
    _valid_artifact_sha256 = field_validator("artifact_sha256")(
        lambda value: _require_sha256(value) if value is not None else value
    )
    _valid_requester_receipt_hash = field_validator("requester_auth_receipt_hash")(
        _require_sha256
    )
    _valid_actor_receipt_hash = field_validator("actor_auth_receipt_hash")(
        _require_sha256
    )
    _aware_created_at = field_validator("created_at")(_require_aware_timestamp)

    @field_validator("delegation_grant_hash")
    @classmethod
    def validate_delegation_grant_hash(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_sha256(value)
        return value

    @model_validator(mode="after")
    def require_learning_policy_and_references(self) -> OutcomeV1:
        if (self.delegation_grant_id is None) != (self.delegation_grant_hash is None):
            raise ValueError(
                "delegation_grant_id and delegation_grant_hash must be provided together"
            )
        if self.continuation_sequence == 0:
            if (
                self.child_result_set_sha256 is not None
                or self.prior_outcome_id is not None
            ):
                raise ValueError(
                    "root continuation outcome must not link prior results"
                )
        elif self.child_result_set_sha256 is None or self.prior_outcome_id is None:
            raise ValueError(
                "child continuation outcome requires linked child results and prior outcome"
            )
        if self.learning_eligible and (
            self.result_kind in _CONTROL_RESULT_KINDS
            or self.classification == "graph_control"
        ):
            raise ValueError("learning_eligible must be false for control outcomes")
        return self


class KernelEventV1(RoutingModel):
    """Immutable event projection from the shared kernel execution trace."""

    version: Literal["artemis.kernel-event/1"] = "artemis.kernel-event/1"
    event_id: str = Field(min_length=1)
    event_type: KernelEventType
    task_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    continuation_sequence: int = Field(ge=0)
    attempt_id: str = Field(min_length=1)
    routing_decision_id: str | None = Field(default=None, min_length=1)
    outcome_id: str | None = Field(default=None, min_length=1)
    provenance_id: str | None = Field(default=None, min_length=1)
    created_at: datetime

    _aware_created_at = field_validator("created_at")(_require_aware_timestamp)

    @model_validator(mode="after")
    def require_terminal_event_references(self) -> KernelEventV1:
        if self.event_type == "complete" and (
            self.outcome_id is None or self.provenance_id is None
        ):
            raise ValueError("complete event requires outcome and provenance IDs")
        return self
