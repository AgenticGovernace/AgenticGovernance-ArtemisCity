"""Authorization tests for the governed Routing Kernel boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.auth.contracts import AuthorityContextV1
from src.auth.delegation import DelegationGrantV1
from src.routing.authorization import ArtemisAuthorizer, AuthorizationDenied
from src.routing.contracts import (
    AuthorizedRouteRequestV1,
    ContinuationV1,
    DelegationContextV1,
    RequestedConstraintsV1,
    ResolvedIntentV1,
    TaskEnvelopeV1,
    TaskIntentV1,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _party(label: str, scopes: set[str], *, tenant: str = "tenant:city") -> dict:
    principal = {
        "identity": {
            "actor_issuer": "https://auth.example.test",
            "actor_subject_ref": f"subject:{label}",
            "agent_id": f"agent:{label}",
            "tenant_id": tenant,
            "certificate_issuer": "issuer:city-ca",
            "certificate_serial": f"serial:{label}",
            "certificate_thumbprint": f"thumbprint:{label}",
            "request_key_id": f"key:{label}",
            "request_key_jkt": f"jkt:{label}",
        },
        "capability": {
            "token_issuer": "https://auth.example.test",
            "audience": "artemis-routing",
            "token_key_id": f"key:capability:{label}",
            "token_jti_ref": f"receipt-ref:{label}",
            "granted_scopes": scopes,
        },
        "verified_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    receipt = {
        "request_id": f"request:{label}",
        "authentication": "authenticated",
        "principal": principal,
        "reason_code": None,
        "verified_at": NOW,
        "source": {
            "format": "authstructure.receipt/2",
            "receipt_id": f"receipt:{label}",
            "record_hash": f"sha256:{label}",
            "receipt_key_id": f"key:receipt:{label}",
            "signer_namespace": "authstructure",
            "canonical_receipt": {"verified": True},
        },
    }
    return {"principal": principal, "auth_receipt": receipt}


def _grant_data(*, scopes: set[str], expires_at: datetime | None = None) -> dict:
    return {
        "version": "artemis.delegation-grant/1",
        "grant_id": "grant:child-1",
        "grant_hash": "pending",
        "root_task_id": "task:root-1",
        "parent_task_id": "task:parent-1",
        "parent_outcome_id": "outcome:parent-1",
        "requester_principal_ref": "agent:requester",
        "requester_auth_receipt_id": "receipt:requester",
        "requester_auth_receipt_hash": "sha256:requester",
        "actor_principal_ref": "agent:actor",
        "actor_auth_receipt_id": "receipt:actor",
        "actor_auth_receipt_hash": "sha256:actor",
        "allowed_modes": frozenset({"Build"}),
        "allowed_action_types": frozenset({"Execute"}),
        "allowed_capabilities": frozenset(scopes),
        "allowed_target_zones": frozenset({"public"}),
        "depth_limit": 1,
        "budget_reservation_id": "budget:child-1",
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": expires_at or NOW + timedelta(minutes=10),
        "policy_version": "artemis.policy/1",
    }


def _grant(
    *, scopes: set[str], expires_at: datetime | None = None
) -> DelegationGrantV1:
    data = _grant_data(scopes=scopes, expires_at=expires_at)
    unsigned = DelegationGrantV1.model_construct(**data)
    data["grant_hash"] = unsigned.canonical_hash()
    return DelegationGrantV1(**data)


def _authority(
    *,
    requester_scopes: set[str],
    actor_scopes: set[str],
    grant: DelegationGrantV1 | None = None,
    reference_hash: str | None = None,
) -> AuthorityContextV1:
    delegation = None
    if grant is not None:
        delegation = {
            "grant_id": grant.grant_id,
            "grant_hash": reference_hash or grant.grant_hash,
        }
    return AuthorityContextV1(
        requester=_party("requester", requester_scopes),
        actor=_party("actor", actor_scopes),
        delegation=delegation,
    )


def _intent(capability: str = "llm_chat") -> ResolvedIntentV1:
    return ResolvedIntentV1(
        mode="Build",
        action_type="Execute",
        context="route a child task",
        target_zone="public",
        source="caller-atp",
        capability=capability,
    )


def _route_request() -> AuthorizedRouteRequestV1:
    authority = _authority(requester_scopes={"llm_chat"}, actor_scopes={"llm_chat"})
    intent = _intent()
    requested = RequestedConstraintsV1()
    envelope = TaskEnvelopeV1(
        task_id="task:root-1",
        generation=0,
        input_sha256="a" * 64,
        ingress="local",
        authority=authority,
        content="route this task",
        intent=TaskIntentV1(
            mode=intent.mode,
            action_type=intent.action_type,
            context=intent.context,
            target_zone=intent.target_zone,
            source=intent.source,
        ),
        requested_constraints=requested,
        delegation=DelegationContextV1(
            grant_id=None,
            grant_hash=None,
            root_task_id="task:root-1",
            parent_task_id=None,
            parent_outcome_id=None,
            depth=0,
        ),
        continuation=ContinuationV1(
            sequence=0,
            child_result_set_sha256=None,
            prior_outcome_id=None,
        ),
        provenance_parent_id=None,
        submission_idempotency_key="submission:root-1",
        attempt_idempotency_key="attempt:root-1",
        created_at=NOW,
    )
    return AuthorizedRouteRequestV1(
        envelope=envelope,
        resolved_intent=intent,
        authority=authority,
    )


def _child_route_request(
    grant: DelegationGrantV1,
    *,
    authority_has_grant: bool = True,
    root_task_id: str = "task:root-1",
) -> AuthorizedRouteRequestV1:
    authority = _authority(
        requester_scopes={"llm_chat", "reasoning"},
        actor_scopes={"llm_chat"},
        grant=grant if authority_has_grant else None,
    )
    intent = _intent()
    requested = RequestedConstraintsV1()
    envelope = TaskEnvelopeV1(
        task_id="task:child-1",
        generation=0,
        input_sha256="a" * 64,
        ingress="scheduler",
        authority=authority,
        content="route this child task",
        intent=TaskIntentV1(
            mode=intent.mode,
            action_type=intent.action_type,
            context=intent.context,
            target_zone=intent.target_zone,
            source=intent.source,
        ),
        requested_constraints=requested,
        delegation=DelegationContextV1(
            grant_id=grant.grant_id,
            grant_hash=grant.grant_hash,
            root_task_id=root_task_id,
            parent_task_id="task:parent-1",
            parent_outcome_id="outcome:parent-1",
            depth=1,
        ),
        continuation=ContinuationV1(
            sequence=1,
            child_result_set_sha256="b" * 64,
            prior_outcome_id="outcome:parent-1",
        ),
        provenance_parent_id="prov:parent-1",
        submission_idempotency_key="submission:child-1",
        attempt_idempotency_key="attempt:child-1",
        created_at=NOW,
    )
    return AuthorizedRouteRequestV1(
        envelope=envelope,
        resolved_intent=intent,
        authority=authority,
    )


class _GrantLookup:
    def __init__(self, grant: DelegationGrantV1 | None, *, broken: bool = False):
        self.grant = grant
        self.broken = broken

    def get(self, grant_id: str) -> DelegationGrantV1 | None:
        if self.broken:
            raise RuntimeError("ledger unavailable")
        if self.grant is not None and self.grant.grant_id == grant_id:
            return self.grant
        return None


class _BudgetPolicy:
    def __init__(self, active: bool = True, *, broken: bool = False):
        self.active = active
        self.broken = broken

    def reservation_is_active(self, reservation_id: str) -> bool:
        if self.broken:
            raise RuntimeError("budget ledger unavailable")
        return self.active and reservation_id == "budget:child-1"


class _CapabilityPolicy:
    def __init__(
        self,
        *,
        target: set[str] | None = None,
        current: set[str] | None = None,
        broken: bool = False,
    ) -> None:
        self.target = frozenset(target or {"llm_chat"})
        self.current = frozenset(current or {"llm_chat"})
        self.broken = broken

    def target_zone_capabilities(self, target_zone: str) -> frozenset[str]:
        if self.broken:
            raise RuntimeError("target policy unavailable")
        return self.target if target_zone == "public" else frozenset()

    def artemis_capabilities(self, intent: ResolvedIntentV1) -> frozenset[str]:
        if self.broken:
            raise RuntimeError("Artemis policy unavailable")
        return self.current


def _authorizer(
    grant: DelegationGrantV1 | None,
    *,
    budget: _BudgetPolicy | None = None,
    policy: _CapabilityPolicy | None = None,
    broken_lookup: bool = False,
) -> ArtemisAuthorizer:
    return ArtemisAuthorizer(
        grant_lookup=_GrantLookup(grant, broken=broken_lookup),
        budget_policy=budget or _BudgetPolicy(),
        capability_policy=policy or _CapabilityPolicy(),
        clock=lambda: NOW,
    )


def test_authorizer_intersects_every_authority_and_policy_layer() -> None:
    """Removing any intersection layer would mint an unauthorized capability."""
    grant = _grant(scopes={"llm_chat", "text_generation"})
    authorized = _authorizer(
        grant,
        policy=_CapabilityPolicy(
            target={"llm_chat", "reasoning"},
            current={"llm_chat", "text_generation"},
        ),
    ).authorize(
        authority=_authority(
            requester_scopes={"llm_chat", "reasoning"},
            actor_scopes={"llm_chat"},
            grant=grant,
        ),
        intent=_intent(),
        requested=RequestedConstraintsV1(),
    )

    assert authorized.capabilities == frozenset({"llm_chat"})
    assert authorized.delegation_grant == grant


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing", "delegation_grant_missing"),
        ("hash", "delegation_grant_hash_mismatch"),
        ("expired", "delegation_grant_expired"),
        ("budget", "delegation_budget_unavailable"),
        ("non_narrowing", "delegation_grant_non_narrowing"),
    ],
)
def test_authorizer_returns_stable_delegation_denials(
    case: str, expected_code: str
) -> None:
    """Collapsing grant failures would erase the durable governance reason."""
    grant = _grant(
        scopes={"llm_chat"},
        expires_at=NOW if case == "expired" else None,
    )
    authority = _authority(
        requester_scopes={"llm_chat", "reasoning"},
        actor_scopes={"llm_chat"},
        grant=grant,
        reference_hash="f" * 64 if case == "hash" else None,
    )
    if case == "non_narrowing":
        intent = _intent("reasoning")
    else:
        intent = _intent()
    authorizer = _authorizer(
        None if case == "missing" else grant,
        budget=_BudgetPolicy(active=case != "budget"),
    )

    with pytest.raises(AuthorizationDenied) as denied:
        authorizer.authorize(authority, intent, RequestedConstraintsV1())

    assert denied.value.code == expected_code


@pytest.mark.parametrize("failure", ["lookup", "budget", "policy"])
def test_authorizer_fails_closed_when_an_admission_port_raises(failure: str) -> None:
    """Port outages must deny rather than fall through to broader authority."""
    grant = _grant(scopes={"llm_chat"})
    authorizer = _authorizer(
        grant,
        budget=_BudgetPolicy(broken=failure == "budget"),
        policy=_CapabilityPolicy(broken=failure == "policy"),
        broken_lookup=failure == "lookup",
    )

    with pytest.raises(AuthorizationDenied) as denied:
        authorizer.authorize(
            _authority(
                requester_scopes={"llm_chat", "reasoning"},
                actor_scopes={"llm_chat"},
                grant=grant,
            ),
            _intent(),
            RequestedConstraintsV1(),
        )

    assert denied.value.code in {
        "delegation_grant_missing",
        "delegation_budget_unavailable",
        "unauthorized_capability",
    }


def test_authorizer_rejects_an_empty_effective_intersection() -> None:
    """Removing the empty-set guard would authorize outside actor scope."""
    with pytest.raises(AuthorizationDenied) as denied:
        _authorizer(None).authorize(
            _authority(
                requester_scopes={"reasoning"},
                actor_scopes={"llm_chat"},
            ),
            _intent(),
            RequestedConstraintsV1(),
        )

    assert denied.value.code == "unauthorized_capability"


def test_authorizer_consumes_the_existing_authorized_route_request_contract() -> None:
    """A kernel route request must not be copied into a competing contract."""
    authorized = _authorizer(None).authorize(_route_request())

    assert authorized.capabilities == frozenset({"llm_chat"})
    assert authorized.intent == _route_request().resolved_intent


def test_child_route_request_requires_matching_authority_delegation() -> None:
    """A child envelope cannot supply a grant absent from verified authority."""
    grant = _grant(scopes={"llm_chat"})

    with pytest.raises(AuthorizationDenied) as denied:
        _authorizer(grant).authorize(
            _child_route_request(grant, authority_has_grant=False)
        )

    assert denied.value.code == "delegation_grant_missing"


def test_child_route_request_must_remain_inside_persisted_grant_links() -> None:
    """Cross-linking a child to another root must fail as non-narrowing."""
    grant = _grant(scopes={"llm_chat"})

    with pytest.raises(AuthorizationDenied) as denied:
        _authorizer(grant).authorize(
            _child_route_request(grant, root_task_id="task:other-root")
        )

    assert denied.value.code == "delegation_grant_non_narrowing"
