"""Contracts for the shared Routing Kernel and its production port adapters.

``src/routing`` defined its inputs as Protocols with no production
implementations, so the authorization and eligibility gates were unreachable
from a running orchestrator and only ever exercised against hand-built fakes.
These tests drive the real adapters against a live registry, trust store, and
sandbox, and assert the ordering property the whole design rests on:
governance and trust eligibility run *before* learned ranking.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.agents.base_agent import BaseAgent
from src.auth.delegation import DelegationGrantV1
from src.integration.agent_registry import AgentRegistry
from src.mcp.hebbian_weights import HebbianWeightManager
from src.routing.adapters import (
    RegistryAdmissionLookup,
    SandboxAdmissionPreflight,
    TrustAdmissionLookup,
)
from src.routing.authorization_policy import (
    AuthorizationPolicyError,
    CapabilityPolicyAdapter,
    ReviewedCapabilityPolicy,
)
from src.routing.contracts import RequestedConstraintsV1
from src.routing.delegation_store import DelegationStoreError, SqliteDelegationStore
from src.routing.kernel import (
    CAPABILITY_OUTSIDE_REVIEWED_DOMAIN,
    RoutingKernel,
    RoutingKernelDenied,
    system_authority,
)

ATP_REVIEW_SUMMARIZE = """#Mode: Review
#Context: Summarize the reviewed notes
#ActionType: Summarize
#TargetZone: docs/

Summarize the reviewed notes for operators.
"""


class _StubAgent(BaseAgent):
    """Minimal registrable agent with a declared capability set."""

    def __init__(self, name: str, capabilities: list[str]):
        super().__init__(name)
        self.capabilities = capabilities

    def perform_task(self, task_context: dict) -> dict:
        return {"summary": f"{self.name} handled the task"}


@pytest.fixture
def registry(tmp_path) -> AgentRegistry:
    """A live registry holding two agents with overlapping capabilities."""
    instance = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    instance.register_agent(_StubAgent("Summary Agent", ["text_summarization"]))
    instance.register_agent(
        _StubAgent("Chat Agent", ["llm_chat", "text_summarization", "reasoning"])
    )
    return instance


class _StubTrust:
    """Trust source returning fixed scores, raising for unknown agents."""

    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def get_trust_score(self, agent_id: str, entity_type: str = "agent"):
        if agent_id not in self._scores:
            raise KeyError(agent_id)
        return type("Score", (), {"score": self._scores[agent_id]})()


@pytest.fixture
def kernel(registry, tmp_path) -> RoutingKernel:
    """A kernel wired to the live registry with all agents fully trusted."""
    return RoutingKernel.build(
        registry,
        HebbianWeightManager(db_path=str(tmp_path / "hebbian.db")),
        trust_interface=_StubTrust({"Summary Agent": 1.0, "Chat Agent": 1.0}),
        delegation_store=SqliteDelegationStore(db_path=str(tmp_path / "delegation.db")),
    )


# ---------------------------------------------------------------------------
# Registry admission projection
# ---------------------------------------------------------------------------


def test_registry_admission_lookup_projects_loaded_agents(registry):
    """Only agents whose classes are loaded become admission records."""
    records = RegistryAdmissionLookup(registry).list_admission_records()

    assert isinstance(records, tuple)
    assert [record.name for record in records] == ["Chat Agent", "Summary Agent"]
    summary = next(r for r in records if r.name == "Summary Agent")
    assert summary.capabilities == frozenset({"text_summarization"})
    assert summary.status == "active"
    assert summary.quarantined is False
    assert 0.0 <= summary.composite_score <= 1.0


def test_registry_admission_lookup_excludes_unloaded_persisted_rows(registry):
    """A persisted row whose class is gone must not become a candidate.

    Routing to such a row would select an agent the orchestrator cannot
    dispatch, which is the same failure ``GET /api/agents`` already guards.
    """
    registry.store.upsert_agent(
        _StubAgent("Ghost Agent", ["text_summarization"]),
        registry.scores["Summary Agent"],
    )
    registry.agents.pop("Summary Agent")

    names = {
        record.name
        for record in RegistryAdmissionLookup(registry).list_admission_records()
    }
    assert "Ghost Agent" not in names
    assert "Summary Agent" not in names
    assert names == {"Chat Agent"}


def test_registry_admission_defaults_scopes_to_declared_capabilities(registry):
    """An unmigrated row must not read as 'scoped to nothing'.

    Eligibility intersects capabilities with scopes, so treating a NULL scope
    grant as the empty set would deny every agent on an existing database.
    """
    records = RegistryAdmissionLookup(registry).list_admission_records()
    chat = next(r for r in records if r.name == "Chat Agent")
    assert chat.scopes == chat.capabilities
    assert chat.tenant_ids == frozenset({"default"})


def test_registry_admission_honors_persisted_scope_and_tenant_grants(registry):
    """Explicit grants narrow the projection."""
    registry.store.set_admission_grants(
        "Chat Agent",
        tenant_ids=["tenant-a"],
        scopes=["llm_chat"],
        agent_uid="uid-chat",
    )
    records = RegistryAdmissionLookup(registry).list_admission_records()
    chat = next(r for r in records if r.name == "Chat Agent")

    assert chat.agent_id == "uid-chat"
    assert chat.tenant_ids == frozenset({"tenant-a"})
    assert chat.scopes == frozenset({"llm_chat"})


def test_registry_admission_reports_quarantine_and_suspension(registry):
    """Governance status is projected into the hard admission flags."""
    registry.set_trust_tier("Chat Agent", "monitored")
    for _ in range(3):
        registry.record_violation("Chat Agent", "unauthorized_tool", {"tool": "x"})

    records = RegistryAdmissionLookup(registry).list_admission_records()
    chat = next(r for r in records if r.name == "Chat Agent")
    assert chat.quarantined is True
    assert chat.status == "quarantined"


# ---------------------------------------------------------------------------
# Trust and sandbox adapters
# ---------------------------------------------------------------------------


def test_trust_admission_lookup_returns_float_score():
    """The adapter unwraps the trust record into a plain float."""
    lookup = TrustAdmissionLookup(_StubTrust({"Chat Agent": 0.75}))
    assert lookup.score("Chat Agent") == pytest.approx(0.75)


def test_trust_admission_lookup_propagates_failure_rather_than_admitting():
    """A trust store that cannot answer must not silently admit an agent."""
    lookup = TrustAdmissionLookup(_StubTrust({}))
    with pytest.raises(KeyError):
        lookup.score("Unknown Agent")


def test_sandbox_preflight_never_records_a_violation(registry):
    """Admission scanning must not penalize a capability mismatch.

    ``AgentSandbox.check_dispatch`` records a violation on a missing
    capability and auto-quarantines on the third strike. Eligibility asks about
    every registered agent, so a preflight built on it would quarantine agents
    for the ordinary act of not matching the requested capability.
    """
    preflight = SandboxAdmissionPreflight(registry)

    for _ in range(5):
        assert (
            preflight.allows("Summary Agent", frozenset({"llm_chat"}), "default")
            is False
        )

    assert registry.is_quarantined("Summary Agent") is False
    assert registry.get_violations("Summary Agent") == []


def test_sandbox_preflight_denies_quarantined_agents(registry):
    """Quarantine is a hard admission stop."""
    preflight = SandboxAdmissionPreflight(registry)
    capability = frozenset({"text_summarization"})
    assert preflight.allows("Summary Agent", capability, "default") is True

    for _ in range(3):
        registry.record_violation("Summary Agent", "unauthorized_tool", {"t": "x"})

    assert preflight.allows("Summary Agent", capability, "default") is False


def test_sandbox_preflight_denies_unknown_agent_and_empty_capability(registry):
    """Unknown agents and empty capability sets fail closed."""
    preflight = SandboxAdmissionPreflight(registry)
    assert preflight.allows("Nobody", frozenset({"llm_chat"}), "default") is False
    assert preflight.allows("Chat Agent", frozenset(), "default") is False


# ---------------------------------------------------------------------------
# Authorization capability policy
# ---------------------------------------------------------------------------


def test_reviewed_capability_policy_loads_shipped_document():
    """The shipped policy document parses and exposes both port methods."""
    adapter = CapabilityPolicyAdapter.load()
    assert "llm_chat" in adapter.policy.artemis_capabilities
    assert "text_summarization" in adapter.target_zone_capabilities("docs/")


def test_capability_policy_first_matching_zone_rule_wins(tmp_path):
    """Ordered rules let an operator narrow a zone above the catch-all."""
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "version: artemis.authorization-policy/1\n"
        "artemis_capabilities: [llm_chat, reasoning]\n"
        "zones:\n"
        "  - pattern: 'secure/*'\n"
        "    capabilities: [reasoning]\n"
        "  - pattern: '*'\n"
        "    capabilities: [llm_chat, reasoning]\n",
        encoding="utf-8",
    )
    adapter = CapabilityPolicyAdapter.load(policy_file)

    assert adapter.target_zone_capabilities("secure/vault") == frozenset({"reasoning"})
    assert adapter.target_zone_capabilities("docs/") == frozenset(
        {"llm_chat", "reasoning"}
    )


def test_capability_policy_without_catch_all_denies_unmatched_zone(tmp_path):
    """An unmatched zone yields no capability rather than widening."""
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "version: artemis.authorization-policy/1\n"
        "artemis_capabilities: [llm_chat]\n"
        "zones:\n"
        "  - pattern: 'secure/*'\n"
        "    capabilities: [llm_chat]\n",
        encoding="utf-8",
    )
    adapter = CapabilityPolicyAdapter.load(policy_file)
    assert adapter.target_zone_capabilities("docs/") == frozenset()


@pytest.mark.parametrize(
    "body",
    [
        "version: wrong/1\nartemis_capabilities: [a]\nzones: []\n",
        "version: artemis.authorization-policy/1\n"
        "artemis_capabilities: []\nzones: []\n",
        "version: artemis.authorization-policy/1\n"
        "artemis_capabilities: [a]\nzones: []\n",
        "version: artemis.authorization-policy/1\nartemis_capabilities: [a]\n",
    ],
)
def test_capability_policy_rejects_malformed_documents(tmp_path, body):
    """A malformed policy fails loudly instead of authorizing nothing quietly."""
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(body, encoding="utf-8")
    with pytest.raises(AuthorizationPolicyError):
        ReviewedCapabilityPolicy.load(policy_file)


def test_capability_policy_reports_missing_document(tmp_path):
    """An absent policy document is an explicit error."""
    with pytest.raises(AuthorizationPolicyError):
        ReviewedCapabilityPolicy.load(tmp_path / "absent.yaml")


# ---------------------------------------------------------------------------
# Delegation ledger
# ---------------------------------------------------------------------------


def _grant(issued_at: datetime, **overrides) -> DelegationGrantV1:
    """Build one hash-consistent delegation grant."""
    fields: dict = {
        "grant_id": "grant-1",
        "root_task_id": "root-1",
        "parent_task_id": "parent-1",
        "parent_outcome_id": "outcome-1",
        "requester_principal_ref": "agent-req",
        "requester_auth_receipt_id": "receipt-req",
        "requester_auth_receipt_hash": "a" * 64,
        "actor_principal_ref": "agent-act",
        "actor_auth_receipt_id": "receipt-act",
        "actor_auth_receipt_hash": "b" * 64,
        "allowed_modes": frozenset({"Review"}),
        "allowed_action_types": frozenset({"Summarize"}),
        "allowed_capabilities": frozenset({"text_summarization"}),
        "allowed_target_zones": frozenset({"docs/"}),
        "depth_limit": 3,
        "budget_reservation_id": "reservation-1",
        "issued_at": issued_at,
        "expires_at": issued_at + timedelta(hours=1),
        "policy_version": "artemis.intent-policy/1",
    }
    fields.update(overrides)
    probe = DelegationGrantV1.model_construct(grant_hash="", **fields)
    return DelegationGrantV1(grant_hash=probe.canonical_hash(), **fields)


@pytest.fixture
def delegation_store(tmp_path) -> SqliteDelegationStore:
    """An isolated delegation ledger."""
    return SqliteDelegationStore(db_path=str(tmp_path / "delegation.db"))


def test_delegation_grant_round_trips_with_types_preserved(delegation_store):
    """A persisted grant reloads as an equal, fully-typed record."""
    grant = _grant(datetime.now(UTC))
    delegation_store.issue(grant)

    loaded = delegation_store.get("grant-1")
    assert loaded == grant
    assert isinstance(loaded.allowed_modes, frozenset)
    assert loaded.expires_at.tzinfo is not None


def test_delegation_grant_reissue_is_idempotent_but_conflict_is_refused(
    delegation_store,
):
    """Retried fan-out is safe; a different grant under one id is not."""
    issued_at = datetime.now(UTC)
    grant = _grant(issued_at)
    delegation_store.issue(grant)
    delegation_store.issue(grant)  # Idempotent replay.

    conflicting = _grant(issued_at, allowed_capabilities=frozenset({"llm_chat"}))
    with pytest.raises(DelegationStoreError):
        delegation_store.issue(conflicting)


def test_tampered_grant_row_fails_integrity_revalidation(delegation_store):
    """Re-validation on read means a hand-edited row cannot load as a grant."""
    delegation_store.issue(_grant(datetime.now(UTC)))
    with sqlite3.connect(delegation_store.db_path) as conn:
        conn.execute(
            "UPDATE delegation_grants SET payload = "
            "REPLACE(payload, 'text_summarization', 'llm_chat___')"
        )
        conn.commit()

    with pytest.raises(DelegationStoreError):
        delegation_store.get("grant-1")


def test_missing_grant_returns_none(delegation_store):
    """An absent grant is ``None``, not an error."""
    assert delegation_store.get("absent") is None
    assert delegation_store.get("") is None


def test_unknown_reservation_is_not_active(delegation_store):
    """Fail closed: an unknown reservation must never read as unlimited."""
    assert delegation_store.reservation_is_active("never-created") is False


def test_reservation_lifecycle_open_consume_exhaust_and_close(delegation_store):
    """A metered reservation stops dispatch once consumed."""
    delegation_store.open_reservation("reservation-1", remaining_units=2)
    assert delegation_store.reservation_is_active("reservation-1") is True

    assert delegation_store.consume_reservation("reservation-1", 1) is True
    assert delegation_store.reservation_is_active("reservation-1") is True

    assert delegation_store.consume_reservation("reservation-1", 1) is False
    assert delegation_store.reservation_is_active("reservation-1") is False


def test_unmetered_reservation_never_exhausts_but_can_be_closed(delegation_store):
    """An unmetered reservation is bounded by explicit release."""
    delegation_store.open_reservation("reservation-2")
    assert delegation_store.consume_reservation("reservation-2", 99) is True
    assert delegation_store.reservation_is_active("reservation-2") is True

    delegation_store.close_reservation("reservation-2")
    assert delegation_store.reservation_is_active("reservation-2") is False


def test_expired_reservation_is_not_active(delegation_store):
    """A past deadline stops dispatch without an explicit release."""
    delegation_store.open_reservation(
        "reservation-3", expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert delegation_store.reservation_is_active("reservation-3") is False


def test_reservation_rejects_naive_deadline(delegation_store):
    """Timezone-naive deadlines are refused rather than assumed UTC."""
    with pytest.raises(DelegationStoreError):
        delegation_store.open_reservation(
            "reservation-4",
            expires_at=datetime(2030, 1, 1),  # noqa: DTZ001
        )


# ---------------------------------------------------------------------------
# System authority
# ---------------------------------------------------------------------------


def test_system_authority_is_identifiable_and_self_delegating():
    """Trusted in-process authority names its issuer for audit."""
    authority = system_authority(granted_scopes=frozenset({"llm_chat"}))

    assert authority.requester == authority.actor
    assert authority.delegation is None
    assert authority.requester.principal.identity.actor_issuer.endswith("/system")
    assert authority.requester.auth_receipt.source.format == (
        "artemis.system-authority/1"
    )


def test_system_authority_requires_at_least_one_scope():
    """An empty scope grant cannot authorize anything, so it is refused."""
    with pytest.raises(ValueError):
        system_authority(granted_scopes=frozenset())


# ---------------------------------------------------------------------------
# Kernel: ordering, gates, and denials
# ---------------------------------------------------------------------------


def test_kernel_routes_atp_task_to_a_capable_agent(kernel):
    """ATP headers resolve capability and rank only eligible candidates."""
    route = kernel.route(
        content=ATP_REVIEW_SUMMARIZE, authority=kernel.system_authority()
    )

    assert route.resolved_intent.capability == "text_summarization"
    assert route.resolved_intent.source == "caller-atp"
    assert route.decision.agent_name in {"Summary Agent", "Chat Agent"}
    assert {c.name for c in route.decision.candidates} == {
        "Summary Agent",
        "Chat Agent",
    }


def test_kernel_excludes_quarantined_agent_before_ranking(kernel, registry):
    """Governance eligibility runs before learned ranking.

    This is the ordering property the design rests on: a quarantined agent must
    never reach the ranker, where a strong Hebbian weight could rescue it.
    """
    for _ in range(3):
        registry.record_violation("Chat Agent", "unauthorized_tool", {"t": "x"})

    route = kernel.route(
        content=ATP_REVIEW_SUMMARIZE, authority=kernel.system_authority()
    )
    assert {c.name for c in route.decision.candidates} == {"Summary Agent"}
    assert route.decision.agent_name == "Summary Agent"


def test_kernel_denies_when_every_candidate_is_quarantined(kernel, registry):
    """An empty eligible pool denies rather than falling back."""
    for name in ("Chat Agent", "Summary Agent"):
        for _ in range(3):
            registry.record_violation(name, "unauthorized_tool", {"t": "x"})

    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route(content=ATP_REVIEW_SUMMARIZE, authority=kernel.system_authority())

    assert denied.value.stage == "eligibility"
    assert denied.value.code == "no_eligible_agent"


def test_kernel_excludes_agents_below_the_trust_floor(registry, tmp_path):
    """Trust filtering happens before ranking, not as a scoring penalty."""
    kernel = RoutingKernel.build(
        registry,
        HebbianWeightManager(db_path=str(tmp_path / "hebbian.db")),
        trust_interface=_StubTrust({"Summary Agent": 0.9, "Chat Agent": 0.1}),
        trust_floor=0.5,
        delegation_store=SqliteDelegationStore(db_path=str(tmp_path / "d.db")),
    )
    route = kernel.route(
        content=ATP_REVIEW_SUMMARIZE, authority=kernel.system_authority()
    )
    assert {c.name for c in route.decision.candidates} == {"Summary Agent"}


def test_kernel_rejects_non_atp_task_without_typed_intent(kernel):
    """A task with neither ATP headers nor a trusted intent is refused."""
    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route(content="just do something", authority=kernel.system_authority())

    assert denied.value.stage == "intent"
    assert denied.value.code == "missing_typed_intent"


def test_kernel_refuses_capability_that_expands_the_atp_domain(kernel):
    """A caller constraint may narrow policy, never widen it."""
    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route(
            content=ATP_REVIEW_SUMMARIZE,
            authority=kernel.system_authority(),
            requested=RequestedConstraintsV1(capability="llm_chat"),
        )

    assert denied.value.stage == "intent"
    assert denied.value.code == "capability_domain_conflict"


# ---------------------------------------------------------------------------
# Kernel: orchestrator compatibility seam
# ---------------------------------------------------------------------------


def test_route_task_context_derives_typed_intent_for_non_atp_task(kernel):
    """A legacy task dict routes via a policy-derived typed-adapter intent."""
    route = kernel.route_task_context(
        {"required_capability": "text_summarization", "content": "summarize this"}
    )

    assert route.resolved_intent.source == "typed-adapter"
    assert route.resolved_intent.capability == "text_summarization"
    assert route.decision.agent_name in {"Summary Agent", "Chat Agent"}


def test_route_task_context_honors_a_pinned_agent(kernel):
    """Pinning selects that agent when it clears every gate."""
    route = kernel.route_task_context(
        {
            "required_capability": "text_summarization",
            "content": "summarize this",
            "agent": "Summary Agent",
        }
    )
    assert route.decision.agent_name == "Summary Agent"


def test_route_task_context_denies_a_pinned_agent_lacking_the_capability(kernel):
    """A bad pin is denied, never silently rerouted to another agent."""
    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route_task_context(
            {
                "required_capability": "reasoning",
                "content": "think",
                "agent": "Summary Agent",
            }
        )

    assert denied.value.stage == "eligibility"
    assert denied.value.code == "pinned_agent_ineligible"


def test_route_task_context_falls_back_when_capability_has_no_agent(kernel):
    """A reviewed capability with no eligible agent may use the fallback."""
    route = kernel.route_task_context(
        {"required_capability": "text_generation", "content": "write"},
        fallback_capability="llm_chat",
    )
    assert route.resolved_intent.capability == "llm_chat"
    assert route.decision.agent_name == "Chat Agent"


def test_capability_outside_reviewed_domain_is_reported_not_rerouted(kernel):
    """An unreviewed capability must not silently become a chat task.

    ``web_search`` has no reviewed ATP execution domain. Falling back to
    ``llm_chat`` would hand a search task to a general chat agent, so the
    kernel surfaces a distinct code and lets the ingress decide.
    """
    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route_task_context(
            {"required_capability": "web_search", "content": "find sources"},
            fallback_capability="llm_chat",
        )

    assert denied.value.code == CAPABILITY_OUTSIDE_REVIEWED_DOMAIN
    assert denied.value.stage == "intent"


def test_typed_intent_for_capability_cannot_widen_the_reviewed_domain(kernel):
    """Intent derivation only ever selects a pair that already allows it."""
    intent = kernel.typed_intent_for_capability(
        "reasoning", context="think carefully", target_zone="docs/"
    )
    domain = kernel.intent_resolver.policy.domain_for(intent.mode, intent.action_type)
    assert "reasoning" in domain

    with pytest.raises(RoutingKernelDenied):
        kernel.typed_intent_for_capability(
            "system_management", context="manage", target_zone="docs/"
        )


def test_routable_capabilities_match_the_reviewed_policy(kernel):
    """The kernel advertises exactly what Artemis policy permits."""
    assert kernel.routable_capabilities == frozenset(
        {"llm_chat", "reasoning", "text_generation", "text_summarization"}
    )


def test_route_task_context_requires_a_capability_for_non_atp_tasks(kernel):
    """Without ATP headers and without a capability there is no intent."""
    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route_task_context({"content": "do something useful"})

    assert denied.value.stage == "intent"
    assert denied.value.code == "missing_typed_intent"


def test_kernel_reports_authorization_stage_denials(kernel, monkeypatch):
    """An authorization refusal is tagged to the authorization stage."""
    from src.routing.authorization import AuthorizationDenied

    def deny(*_args, **_kwargs):
        raise AuthorizationDenied("unauthorized_capability", "policy refused")

    monkeypatch.setattr(kernel.authorizer, "authorize", deny)

    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route(content=ATP_REVIEW_SUMMARIZE, authority=kernel.system_authority())

    assert denied.value.stage == "authorization"
    assert denied.value.code == "unauthorized_capability"


def test_kernel_routes_an_authorized_route_request(kernel):
    """A pre-authorized route request replaces the split authority inputs.

    This is the shape a delegated child task arrives in: authority, envelope,
    and resolved intent already bound together and verified upstream.
    """
    from src.routing.contracts import (
        AuthorizedRouteRequestV1,
        ContinuationV1,
        DelegationContextV1,
        ResolvedIntentV1,
        TaskEnvelopeV1,
        TaskIntentV1,
    )

    authority = kernel.system_authority()
    intent = TaskIntentV1(
        mode="Review",
        action_type="Summarize",
        context="Summarize the reviewed notes",
        target_zone="docs/",
        source="caller-atp",
    )
    envelope = TaskEnvelopeV1(
        task_id="task-1",
        generation=0,
        input_sha256="d" * 64,
        ingress="test",
        authority=authority,
        content="Summarize the reviewed notes for operators.",
        intent=intent,
        requested_constraints=RequestedConstraintsV1(),
        delegation=DelegationContextV1(root_task_id="task-1", depth=0),
        continuation=ContinuationV1(sequence=0),
        submission_idempotency_key="submit-1",
        attempt_idempotency_key="attempt-1",
        created_at=datetime.now(UTC),
    )
    request = AuthorizedRouteRequestV1(
        envelope=envelope,
        resolved_intent=ResolvedIntentV1(
            **intent.model_dump(), capability="text_summarization"
        ),
        authority=authority,
    )

    route = kernel.route(
        content=ATP_REVIEW_SUMMARIZE,
        authority=authority,
        route_request=request,
    )
    assert route.resolved_intent.capability == "text_summarization"
    assert route.decision.agent_name in {"Summary Agent", "Chat Agent"}


def test_kernel_reports_ranking_stage_failures(kernel, monkeypatch):
    """A ranker contract violation surfaces as a ranking-stage denial."""

    def explode(*_args, **_kwargs):
        raise ValueError("candidate tuple contains unauthorized capabilities")

    monkeypatch.setattr(kernel.ranker, "rank", explode)

    with pytest.raises(RoutingKernelDenied) as denied:
        kernel.route(content=ATP_REVIEW_SUMMARIZE, authority=kernel.system_authority())

    assert denied.value.stage == "ranking"
    assert denied.value.code == "ranking_failed"


# ---------------------------------------------------------------------------
# Adapter edge cases
# ---------------------------------------------------------------------------


def test_registry_admission_lookup_rejects_a_blank_default_tenant(registry):
    """A blank default tenant would admit agents into an unnamed tenant."""
    with pytest.raises(ValueError):
        RegistryAdmissionLookup(registry, default_tenant_id="   ")


def test_registry_admission_lookup_returns_empty_for_an_empty_registry(tmp_path):
    """No loaded agents means no admission records, not an error."""
    empty = AgentRegistry(db_path=str(tmp_path / "empty.db"))
    assert RegistryAdmissionLookup(empty).list_admission_records() == ()


def test_registry_admission_skips_agents_declaring_no_capability(registry):
    """A capability-less agent can never be selected, so it is not a record."""
    registry.register_agent(_StubAgent("Mute Agent", []))
    names = {
        record.name
        for record in RegistryAdmissionLookup(registry).list_admission_records()
    }
    assert "Mute Agent" not in names


def test_registry_admission_falls_back_to_in_memory_score(registry, monkeypatch):
    """A persisted row without a composite still yields a usable score."""
    monkeypatch.setattr(registry.store, "list_admission_records", lambda: [])

    records = RegistryAdmissionLookup(registry).list_admission_records()
    assert records
    assert all(0.0 <= record.composite_score <= 1.0 for record in records)


def test_registry_admission_clamps_an_unusable_composite_score(registry, monkeypatch):
    """A corrupt score must not propagate into ranking as NaN or a string."""
    monkeypatch.setattr(
        registry.store,
        "list_admission_records",
        lambda: [
            {
                "name": "Chat Agent",
                "agent_uid": None,
                "capabilities": ["llm_chat"],
                "tenant_ids": [],
                "scopes": [],
                "status": "active",
                "composite_score": "not-a-number",
            }
        ],
    )
    records = RegistryAdmissionLookup(registry).list_admission_records()
    chat = next(r for r in records if r.name == "Chat Agent")
    assert chat.composite_score == 0.0


# ---------------------------------------------------------------------------
# Policy document edge cases
# ---------------------------------------------------------------------------


def test_capability_policy_rejects_unparseable_yaml(tmp_path):
    """A YAML syntax error is reported as a policy error, not a raw parse error."""
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text("version: [unclosed\n", encoding="utf-8")
    with pytest.raises(AuthorizationPolicyError):
        ReviewedCapabilityPolicy.load(policy_file)


@pytest.mark.parametrize(
    "zone_block",
    [
        "  - capabilities: [llm_chat]\n",  # missing pattern
        "  - pattern: ''\n    capabilities: [llm_chat]\n",  # blank pattern
        "  - [not, a, mapping]\n",  # wrong node type
    ],
)
def test_capability_policy_rejects_malformed_zone_rules(tmp_path, zone_block):
    """Every zone rule needs exactly a non-empty pattern and capabilities."""
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "version: artemis.authorization-policy/1\n"
        "artemis_capabilities: [llm_chat]\n"
        "zones:\n" + zone_block,
        encoding="utf-8",
    )
    with pytest.raises(AuthorizationPolicyError):
        ReviewedCapabilityPolicy.load(policy_file)


def test_capability_policy_rejects_a_blank_target_zone():
    """An empty target zone cannot be matched against any rule."""
    adapter = CapabilityPolicyAdapter.load()
    with pytest.raises(AuthorizationPolicyError):
        adapter.target_zone_capabilities("   ")


# ---------------------------------------------------------------------------
# Delegation ledger edge cases
# ---------------------------------------------------------------------------


def test_delegation_store_refuses_non_grant_and_hash_mismatch(delegation_store):
    """Only hash-consistent ``DelegationGrantV1`` records are storable."""
    with pytest.raises(DelegationStoreError):
        delegation_store.issue({"grant_id": "grant-1"})

    grant = _grant(datetime.now(UTC))
    tampered = grant.model_copy(update={"grant_hash": "c" * 64})
    with pytest.raises(DelegationStoreError):
        delegation_store.issue(tampered)


def test_reservation_open_validates_its_inputs(delegation_store):
    """Blank ids and negative budgets are refused up front."""
    with pytest.raises(DelegationStoreError):
        delegation_store.open_reservation("   ")
    with pytest.raises(DelegationStoreError):
        delegation_store.open_reservation("reservation-9", remaining_units=-1)
    with pytest.raises(DelegationStoreError):
        delegation_store.consume_reservation("reservation-9", -1)


def test_reservation_with_unparseable_deadline_is_not_active(delegation_store):
    """A corrupt stored deadline fails closed rather than admitting."""
    delegation_store.open_reservation("reservation-5")
    with sqlite3.connect(delegation_store.db_path) as conn:
        conn.execute(
            "UPDATE budget_reservations SET expires_at = 'not-a-timestamp' "
            "WHERE reservation_id = ?",
            ("reservation-5",),
        )
        conn.commit()
    assert delegation_store.reservation_is_active("reservation-5") is False


def test_reservation_with_naive_stored_deadline_is_not_active(delegation_store):
    """A stored deadline without a timezone is unusable, so dispatch stops."""
    delegation_store.open_reservation("reservation-6")
    with sqlite3.connect(delegation_store.db_path) as conn:
        conn.execute(
            "UPDATE budget_reservations SET expires_at = '2099-01-01T00:00:00' "
            "WHERE reservation_id = ?",
            ("reservation-6",),
        )
        conn.commit()
    assert delegation_store.reservation_is_active("reservation-6") is False


def test_consuming_an_unknown_reservation_reports_inactive(delegation_store):
    """Consuming a reservation that does not exist cannot activate it."""
    assert delegation_store.consume_reservation("absent", 1) is False


def test_consuming_an_inactive_reservation_reports_inactive(delegation_store):
    """A released reservation cannot be revived by consuming from it."""
    delegation_store.open_reservation("reservation-7", remaining_units=5)
    delegation_store.close_reservation("reservation-7")
    assert delegation_store.consume_reservation("reservation-7", 1) is False


def test_reservation_is_active_rejects_a_blank_identifier(delegation_store):
    """A blank reservation id can never identify an active reservation."""
    assert delegation_store.reservation_is_active("") is False
    assert delegation_store.reservation_is_active("   ") is False


def test_reservation_opened_with_zero_units_is_already_exhausted(delegation_store):
    """A zero-unit reservation must not authorize a single dispatch."""
    delegation_store.open_reservation("reservation-8", remaining_units=0)
    assert delegation_store.reservation_is_active("reservation-8") is False


def test_delegation_store_reports_an_unusable_ledger_at_construction(tmp_path):
    """A ledger path that cannot hold a database fails loudly at boot."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    with pytest.raises(DelegationStoreError):
        SqliteDelegationStore(db_path=str(blocked))


@pytest.mark.parametrize(
    "operation",
    [
        lambda store: store.get("grant-1"),
        lambda store: store.issue(_grant(datetime.now(UTC))),
        lambda store: store.reservation_is_active("reservation-1"),
        lambda store: store.open_reservation("reservation-1"),
        lambda store: store.consume_reservation("reservation-1", 1),
        lambda store: store.close_reservation("reservation-1"),
    ],
)
def test_every_ledger_operation_surfaces_a_database_failure(
    delegation_store, monkeypatch, operation
):
    """A failing ledger must raise, never quietly report 'no grant'/'inactive'.

    Silently returning ``None`` or ``False`` here would be indistinguishable
    from a legitimate denial, so an operator could not tell an outage from a
    policy decision.
    """

    def broken_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(delegation_store, "_connect", broken_connect)

    with pytest.raises(DelegationStoreError):
        operation(delegation_store)


# ---------------------------------------------------------------------------
# Registry admission persistence
# ---------------------------------------------------------------------------


def test_set_admission_grants_without_values_is_a_no_op(registry):
    """Calling with nothing to set must not issue an empty UPDATE."""
    registry.store.set_admission_grants("Chat Agent")
    records = registry.store.list_admission_records()
    chat = next(r for r in records if r["name"] == "Chat Agent")
    assert chat["tenant_ids"] == []
    assert chat["scopes"] == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        (["a", "b"], ["a", "b"]),
        (("a",), ["a"]),
        ('["a", "b"]', ["a", "b"]),
        ("not json", []),
        ('{"a": 1}', []),
        ("null", []),
    ],
)
def test_decode_json_list_tolerates_legacy_and_corrupt_rows(raw, expected):
    """Admission decoding never raises on a legacy or damaged column."""
    from src.integration.agent_registry import AgentRegistryStore

    assert AgentRegistryStore._decode_json_list(raw) == expected


# ---------------------------------------------------------------------------
# Orchestrator integration seam
# ---------------------------------------------------------------------------


def _orchestrator_shell(kernel_obj, fallback="llm_chat"):
    """Build a minimal orchestrator exposing only the routing collaborators.

    The legacy router double returns a real ``RoutingDecision`` because the
    orchestrator labels the decision it gets back; a stand-in that cannot
    carry ``routing_path`` would hide that the label was ever applied.
    """
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src.integration.hebbian_router import RoutingDecision
    from src.mcp.orchestrator import Orchestrator

    shell = Orchestrator.__new__(Orchestrator)
    shell.routing_kernel = kernel_obj
    shell.routing_kernel_enabled = kernel_obj is not None
    shell.hebbian_router = SimpleNamespace(
        fallback_capability=fallback,
        route=Mock(
            side_effect=lambda _task: RoutingDecision(
                agent_name="legacy-decision", alpha=0.3
            )
        ),
    )
    return shell


def test_orchestrator_uses_the_legacy_router_when_no_kernel_is_built():
    """A boot-time kernel failure must not make the orchestrator unroutable."""
    shell = _orchestrator_shell(None)
    decision = shell.route_task({"required_capability": "llm_chat"})
    assert decision.agent_name == "legacy-decision"
    # The fallback reason must be visible to callers, not just to the log.
    assert decision.routing_path == "legacy_kernel_unavailable"
    shell.hebbian_router.route.assert_called_once()


def test_orchestrator_returns_the_kernel_decision(kernel):
    """With a kernel present, its decision is what callers receive."""
    shell = _orchestrator_shell(kernel)
    decision = shell.route_task(
        {"required_capability": "text_summarization", "content": "summarize"}
    )
    assert decision.agent_name in {"Summary Agent", "Chat Agent"}
    # The kernel stamps its own decisions, so an authorized route is
    # identifiable regardless of which ingress asked for it.
    assert decision.routing_path == "kernel"
    shell.hebbian_router.route.assert_not_called()


def test_orchestrator_translates_kernel_denials_into_value_error(kernel, registry):
    """A genuine denial propagates as ValueError carrying the stable code."""
    for name in ("Chat Agent", "Summary Agent"):
        for _ in range(3):
            registry.record_violation(name, "unauthorized_tool", {"t": "x"})

    shell = _orchestrator_shell(kernel, fallback=None)
    with pytest.raises(ValueError, match="no_eligible_agent"):
        shell.route_task(
            {"required_capability": "text_summarization", "content": "summarize"}
        )


def test_orchestrator_falls_back_for_capabilities_outside_the_reviewed_domain(kernel):
    """Agents advertising unreviewed capabilities keep the legacy path.

    ``web_search`` has no reviewed ATP domain, so the kernel cannot authorize
    it. Regressing Research Agent to unroutable would be a silent capability
    loss, so the orchestrator routes it legacily and logs the gap.
    """
    shell = _orchestrator_shell(kernel)
    decision = shell.route_task(
        {"required_capability": "web_search", "content": "find"}
    )
    assert decision.agent_name == "legacy-decision"
    # The gap is named specifically, so it stays distinguishable from a kernel
    # that simply failed to build.
    assert decision.routing_path == "legacy_unreviewed_capability"
    shell.hebbian_router.route.assert_called_once()


def _boot_orchestrator(monkeypatch, tmp_path):
    """Boot a real Orchestrator with only its vault/vector deps mocked."""
    from unittest.mock import Mock, patch

    from src.mcp import config as mcp_config
    from src.mcp.orchestrator import Orchestrator

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ARTEMIS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(mcp_config, "OBSIDIAN_VAULT_PATH", str(vault))

    vector_store = Mock()
    vector_store.count.return_value = 0
    with (
        patch("src.mcp.orchestrator.ObsidianManager"),
        patch("src.mcp.orchestrator.ObsidianParser"),
        patch("src.mcp.orchestrator.ObsidianGenerator"),
        patch("src.mcp.orchestrator.MemoryBus"),
    ):
        return Orchestrator(vector_store=vector_store)


def test_orchestrator_boot_builds_a_routing_kernel(monkeypatch, tmp_path):
    """The kernel is the default routing path for a healthy boot."""
    orchestrator = _boot_orchestrator(monkeypatch, tmp_path)
    assert orchestrator.routing_kernel is not None
    assert orchestrator.routing_kernel_enabled is True


def test_orchestrator_boot_survives_an_unbuildable_kernel(monkeypatch, tmp_path):
    """A damaged policy document must not stop the orchestrator from booting.

    Kernel construction reads a policy document and opens the delegation
    ledger. Either can fail on a misconfigured host, and an orchestrator that
    refused to boot would be a worse outcome than one that routes legacily.
    """
    import src.routing.kernel as kernel_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("policy document is unreadable")

    monkeypatch.setattr(kernel_module.RoutingKernel, "build", explode)

    orchestrator = _boot_orchestrator(monkeypatch, tmp_path)
    assert orchestrator.routing_kernel is None
    assert orchestrator.hebbian_router is not None


def test_orchestrator_kernel_can_be_disabled_by_environment(monkeypatch, tmp_path):
    """``ARTEMIS_ROUTING_KERNEL=0`` restores the legacy-only routing path."""
    monkeypatch.setenv("ARTEMIS_ROUTING_KERNEL", "0")
    orchestrator = _boot_orchestrator(monkeypatch, tmp_path)
    assert orchestrator.routing_kernel_enabled is False
    assert orchestrator.routing_kernel is None
