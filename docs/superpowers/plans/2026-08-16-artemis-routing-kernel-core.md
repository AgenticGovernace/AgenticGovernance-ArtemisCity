# Artemis Governed Routing Kernel Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the credential-free authority contracts and one transport-independent Routing Kernel that authenticates, resolves strict ATP intent, authorizes, filters eligibility, ranks, dispatches, and finalizes every Artemis task.

**Architecture:** Authstructure is consumed through a narrow verifier port that returns signed, credential-free receipts. Artemis derives the routing domain from strict ATP or a trusted typed adapter, intersects that domain with verified authority and policy, then lets Hebbian evidence rank only the eligible candidates. Synchronous and streaming calls share one lifecycle; transports remain adapters.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, existing ATP parser/validator, existing registry/sandbox/Hebbian ports

**Spec:** `docs/superpowers/specs/2026-08-16-artemis-routing-kernel-consolidation-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-16-artemis-routing-kernel-containment.md`

## Global Constraints

- Authentication precedes ATP parsing, authorization, routing, agent execution, persistence, and learning.
- Authstructure authenticates identities and request proof; Artemis alone authorizes capabilities, agents, paths, and operations.
- Caller input may narrow an ATP-derived capability domain; it cannot expand or replace that domain.
- Caller payloads cannot construct trusted authority, principals, auth receipts, or delegation grants.
- Raw credentials, bearer tokens, certificate material, private keys, authorization codes, and provider secrets never enter domain models, logs, errors, outcomes, or provenance.
- Governance and trust determine eligibility before Hebbian ranking. Hebbian evidence never grants authority.
- SEED and notebook values are experiment/reproduction metadata only; they never enter production authorization, routing, trust, or learning policy.
- `RoutingKernel.execute()` and `RoutingKernel.stream()` share preparation, dispatch, and finalization code.
- Production wiring stays disabled until Authstructure publishes the external verifier/receipt contract and its conformance tests pass.
- New and touched code follows `docs/CODING_STANDARDS.md`: Black at 88 characters, typed boundaries, focused modules, fail-closed errors, and no unrelated mass formatting.
- Tests use the repository safety fixtures and disposable paths; they never touch live data, logs, databases, or the Obsidian vault.
- Preserve unrelated staged, unstaged, and untracked work. Stage and commit only the paths named by each task.

---

### Task 1: Define canonical authentication and authority contracts

**Files:**
- Create: `src/auth/__init__.py`
- Create: `src/auth/contracts.py`
- Create: `src/auth/delegation.py`
- Create: `src/tests/test_auth_contracts.py`

**Interfaces:**
- Consumes: Authstructure's future credential-free receipt projection.
- Produces: `PrincipalIdentityV1`, `PrincipalCapabilityV1`, `PrincipalV1`, `AuthReceiptSourceV1`, `AuthReceiptV1`, `VerifiedPartyV1`, `DelegationReferenceV1`, `AuthorityContextV1`, `DelegationGrantV1`, and `DelegationGrantLookup`.

The exact fields are:

| Model | Fields |
|---|---|
| `PrincipalIdentityV1` | `actor_issuer`, `actor_subject_ref`, `agent_id`, `tenant_id`, `certificate_issuer`, `certificate_serial`, `certificate_thumbprint`, `request_key_id`, `request_key_jkt` |
| `PrincipalCapabilityV1` | `token_issuer`, `audience`, `token_key_id`, `token_jti_ref`, `granted_scopes` |
| `PrincipalV1` | literal `version="artemis.principal/1"`, `identity`, `capability`, `verified_at`, `expires_at` |
| `AuthReceiptSourceV1` | `format`, `receipt_id`, `record_hash`, `receipt_key_id`, `signer_namespace`, `canonical_receipt` |
| `AuthReceiptV1` | literal `version="artemis.auth-receipt/1"`, `request_id`, `authentication`, `principal`, `reason_code`, `verified_at`, `source` |
| `VerifiedPartyV1` | `principal`, `auth_receipt` |
| `DelegationReferenceV1` | `grant_id`, `grant_hash` |
| `AuthorityContextV1` | `requester`, `actor`, `delegation` |
| `DelegationGrantV1` | literal `version="artemis.delegation-grant/1"`, `grant_id`, `grant_hash`, root/parent/outcome IDs, requester/actor principal and receipt refs/hashes, allowed modes/action types/capabilities/target zones, depth limit, budget reservation ID, issue/expiry times, policy version |

- [ ] **Step 1: Write failing contract tests**

  Add tests with literal timezone-aware fixtures. The core assertions are:

  ```python
  def test_authenticated_receipt_requires_unexpired_principal(now, principal_data):
      principal_data["expires_at"] = now
      with pytest.raises(ValidationError, match="expires_at"):
          authenticated_receipt(now=now, principal_data=principal_data)


  def test_rejected_receipt_cannot_carry_principal(now, principal_data):
      with pytest.raises(ValidationError, match="rejected receipt"):
          AuthReceiptV1(
              request_id="req-1",
              authentication="rejected",
              principal=PrincipalV1(**principal_data),
              reason_code="invalid_request_proof",
              verified_at=now,
              source=receipt_source(),
          )


  @pytest.mark.parametrize(
      "field",
      ["token", "api_key", "private_key", "authorization_code", "certificate_pem"],
  )
  def test_authority_models_reject_secret_aliases(field, root_authority_data):
      root_authority_data[field] = "secret"
      with pytest.raises(ValidationError, match=field):
          AuthorityContextV1(**root_authority_data)
  ```

- [ ] **Step 2: Run the tests to verify RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_auth_contracts.py -q
  ```

  Expected: collection fails because `src.auth.contracts` does not exist.

- [ ] **Step 3: Implement strict frozen models and cross-field validation**

  Use one base model and normalize scopes before validation:

  ```python
  class AuthorityModel(BaseModel):
      """Strict immutable base for credential-free authority records."""

      model_config = ConfigDict(
          extra="forbid",
          frozen=True,
          str_strip_whitespace=True,
      )


  class PrincipalCapabilityV1(AuthorityModel):
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
  ```

  `PrincipalV1` rejects naïve timestamps and requires `expires_at > verified_at`.
  `AuthReceiptV1` enforces these exact states:

  - `authenticated`: non-null principal, null reason code, receipt verification time not after principal expiry.
  - `rejected`: null principal and a non-empty registered reason code.

  `AuthorityContextV1` requires requester and actor receipts to be authenticated. A root factory in Task 5 is the only production constructor that sets requester equal to actor.

  `DelegationGrantLookup` exposes `get(grant_id: str) -> DelegationGrantV1 | None`.
  The grant model is an immutable ledger record, not a bearer token, and its
  `grant_hash` is verified against canonical model bytes excluding that hash.

- [ ] **Step 4: Run contract tests and formatting**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_auth_contracts.py -q
  .venv/bin/python -m black --check src/auth src/tests/test_auth_contracts.py
  ```

  Expected: all tests pass and Black reports no changes required.

- [ ] **Step 5: Commit the authority contracts**

  ```bash
  git add src/auth/__init__.py src/auth/contracts.py src/auth/delegation.py \
    src/tests/test_auth_contracts.py
  git commit -m "feat(auth): define credential-free authority contracts"
  ```

---

### Task 2: Define routing, result, and event contracts

**Files:**
- Create: `src/routing/__init__.py`
- Create: `src/routing/contracts.py`
- Create: `src/tests/test_routing_contracts.py`

**Interfaces:**
- Consumes: `AuthorityContextV1` from Task 1.
- Produces: `TaskSubmissionV1`, `TaskIntentV1`, `RequestedConstraintsV1`, `DelegationContextV1`, `ContinuationV1`, `TaskEnvelopeV1`, `ResolvedIntentV1`, `AuthorizedRouteRequestV1`, `RoutingDecisionV1`, `OutcomeV1`, and `KernelEventV1`.

- [ ] **Step 1: Write failing envelope and outcome tests**

  Cover unknown-field rejection, SHA-256 format, root continuation invariants,
  caller authority rejection at the transport shape, unknown result status, and
  explicit learning eligibility:

  ```python
  def test_transport_submission_rejects_authority_alias(valid_submission):
      valid_submission["authority"] = {"principal": "caller-created"}
      with pytest.raises(ValidationError, match="authority"):
          TaskSubmissionV1(**valid_submission)


  def test_root_envelope_requires_zero_continuation(valid_envelope):
      valid_envelope["continuation"] = {
          "sequence": 1,
          "child_result_set_sha256": None,
          "prior_outcome_id": None,
      }
      with pytest.raises(ValidationError, match="root continuation"):
          TaskEnvelopeV1(**valid_envelope)


  def test_outcome_rejects_unknown_status(valid_outcome):
      valid_outcome["status"] = "done"
      with pytest.raises(ValidationError, match="status"):
          OutcomeV1(**valid_outcome)
  ```

- [ ] **Step 2: Run the tests to verify RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_routing_contracts.py -q
  ```

  Expected: collection fails because `src.routing.contracts` does not exist.

- [ ] **Step 3: Implement the exact versioned shapes**

  Use strict frozen Pydantic models. `TaskEnvelopeV1` carries the fields approved
  in the spec: version, task/generation/input identity, ingress, trusted
  authority, content, intent, requested constraints, delegation, continuation,
  provenance parent, both idempotency keys, and `created_at`.

  Use these closed literals:

  ```python
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
  ```

  `OutcomeV1` requires stable outcome, attempt, task, generation, continuation,
  content/artifact hashes, routing decision, authority/grant references,
  provenance IDs, retryability, and `learning_eligible`. Planning, checkpoint,
  and graph-control classifications validate as learning-ineligible.

- [ ] **Step 4: Run tests, type checking, and formatting**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_routing_contracts.py -q
  .venv/bin/python -m mypy src/auth/contracts.py src/routing/contracts.py
  .venv/bin/python -m black --check src/auth src/routing \
    src/tests/test_auth_contracts.py src/tests/test_routing_contracts.py
  ```

  Expected: all commands pass.

- [ ] **Step 5: Commit routing contracts**

  ```bash
  git add src/routing/__init__.py src/routing/contracts.py \
    src/tests/test_routing_contracts.py
  git commit -m "feat(routing): define task and outcome contracts"
  ```

---

### Task 3: Make ATP intent resolution authoritative and non-downgradeable

**Files:**
- Create: `src/routing/intent.py`
- Create: `src/routing/policy.py`
- Create: `config/routing/intent-policy.v1.yaml`
- Create: `src/tests/test_routing_intent.py`
- Modify: `src/agents/atp/atp_context.py`
- Modify: `src/tests/test_atp_context.py`
- Modify: `src/tests/test_atp_validator.py`

**Interfaces:**
- Consumes: `TaskIntentV1`, `RequestedConstraintsV1`, `ATPParser`, and `ATPValidator(strict=True)`.
- Produces: `IntentPolicy.load(path)`, `IntentResolver.resolve(content, typed_intent, requested) -> ResolvedIntentV1`, and stable `IntentDenied(code, message)` errors.

- [ ] **Step 1: Write the failing strict-domain tests**

  Add literal tests for these cases:

  ```python
  def test_review_summarize_cannot_expand_to_memory_write(resolver):
      with pytest.raises(IntentDenied) as denied:
          resolver.resolve(
              content=ATP_REVIEW_SUMMARIZE,
              typed_intent=None,
              requested=RequestedConstraintsV1(capability="memory:write"),
          )
      assert denied.value.code == "capability_domain_conflict"


  def test_atp_presence_always_uses_strict_validation(resolver):
      with pytest.raises(IntentDenied) as denied:
          resolver.resolve(
              content=ATP_COMMIT_REFLECT,
              typed_intent=None,
              requested=RequestedConstraintsV1(),
          )
      assert denied.value.code == "invalid_atp"


  def test_typed_adapter_is_rejected_when_atp_headers_are_present(resolver):
      with pytest.raises(IntentDenied) as denied:
          resolver.resolve(
              content=ATP_REVIEW_SUMMARIZE,
              typed_intent=execute_chat_intent(),
              requested=RequestedConstraintsV1(),
          )
      assert denied.value.code == "ambiguous_intent_source"
  ```

  Replace the current `test_atp_context` expectation that an explicit
  capability wins. The new expected behavior is equality/narrowing or denial.

- [ ] **Step 2: Run the focused tests to verify RED**

  Run:

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_routing_intent.py \
    src/tests/test_atp_context.py \
    src/tests/test_atp_validator.py
  ```

  Expected: new tests fail because explicit capability currently wins and the
  shared resolver does not exist.

- [ ] **Step 3: Add an explicit versioned intent policy**

  The policy file contains no keyword rules. It maps only valid ATP pairs to an
  allowed capability domain and defines named target-zone policies. Seed it
  with the capabilities already declared by maintained agents:

  ```yaml
  version: artemis.intent-policy/1
  pairs:
    Build:
      Scaffold: [text_generation]
      Execute: [llm_chat]
    Review:
      Summarize: [text_summarization]
      Reflect: [reasoning]
    Organize:
      Scaffold: [text_generation]
      Execute: [llm_chat]
    Capture:
      Summarize: [text_summarization]
    Synthesize:
      Summarize: [text_summarization]
      Reflect: [reasoning]
    Commit:
      Execute: [llm_chat]
    Reflect:
      Reflect: [reasoning]
      Summarize: [text_summarization]
  fallback:
    capability: llm_chat
    allowed_pairs:
      - [Build, Execute]
      - [Organize, Execute]
      - [Commit, Execute]
  ```

  A later reviewed policy version can add memory-specific capabilities. Do not
  infer `memory:*` authority merely because a target string contains the word
  `memory`.

- [ ] **Step 4: Implement strict resolution and narrow constraints**

  The resolver algorithm is exactly:

  ```python
  domain = policy.domain_for(message.mode.value, message.action_type.value)
  if not domain:
      raise IntentDenied("invalid_atp", "ATP pair has no execution domain")
  requested_capability = requested.capability
  if requested_capability is not None and requested_capability not in domain:
      raise IntentDenied(
          "capability_domain_conflict",
          "requested capability expands the ATP-authorized domain",
      )
  selected = requested_capability or policy.default_for(domain)
  ```

  ATP headers always use `ATPValidator(strict=True)`. When headers are absent,
  require a typed adapter intent and record `source="typed-adapter"`. Remove the
  `strict` argument and explicit-capability-first behavior from the production
  path in `atp_context.py`; retain an advisory preview helper only if an active
  authoring client uses it.

- [ ] **Step 5: Run intent tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_routing_intent.py \
    src/tests/test_atp_context.py \
    src/tests/test_atp_validator.py
  git add config/routing/intent-policy.v1.yaml src/routing/intent.py \
    src/routing/policy.py src/agents/atp/atp_context.py \
    src/tests/test_routing_intent.py src/tests/test_atp_context.py \
    src/tests/test_atp_validator.py
  git commit -m "feat(routing): derive capability from strict ATP"
  ```

---

### Task 4: Authorize and filter eligibility before learned ranking

**Files:**
- Create: `src/routing/authorization.py`
- Create: `src/routing/eligibility.py`
- Create: `src/tests/test_routing_authorization.py`
- Create: `src/tests/test_routing_eligibility.py`
- Modify: `src/integration/hebbian_router.py`
- Modify: `src/tests/test_hebbian_router.py`

**Interfaces:**
- Consumes: verified `AuthorityContextV1`, `ResolvedIntentV1`, Artemis policy, registry records, trust, quarantine, sandbox policy, and `DelegationGrantLookup`.
- Produces: `ArtemisAuthorizer.authorize`, `EligibilityFilter.candidates`, and `HebbianRanker.rank` with the typed returns defined below.

- [ ] **Step 1: Write failing intersection and ranking-boundary tests**

  Assert requester `{llm_chat, reasoning}`, actor `{llm_chat}`, and grant
  `{llm_chat, text_generation}` produce only `{llm_chat}`. Add tests proving a
  pinned quarantined agent is denied and that a high Hebbian score cannot
  reintroduce an ineligible candidate.

  ```python
  def test_authorizer_intersects_requester_actor_and_grant(authorizer):
      authorized = authorizer.authorize(
          authority=authority(
              requester_scopes={"llm_chat", "reasoning"},
              actor_scopes={"llm_chat"},
              grant_scopes={"llm_chat", "text_generation"},
          ),
          intent=resolved_intent(domain={"llm_chat"}),
          requested=RequestedConstraintsV1(),
      )
      assert authorized.capabilities == frozenset({"llm_chat"})


  def test_ranker_never_receives_quarantined_candidate(filter_, ranker):
      candidates = filter_.candidates(authorized_request(), registry_with_quarantine())
      ranker.rank(authorized_request(), candidates)
      assert [candidate.name for candidate in ranker.seen] == ["eligible-agent"]
  ```

- [ ] **Step 2: Run focused tests to verify RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_routing_authorization.py \
    src/tests/test_routing_eligibility.py \
    src/tests/test_hebbian_router.py
  ```

  Expected: the new modules are missing and the existing router still owns
  fallback/eligibility decisions.

- [ ] **Step 3: Implement authority intersection and stable denials**

  Intersect, in order, requester scopes, actor scopes, persisted grant scopes
  when present, ATP capability domain, target-zone policy, and current Artemis
  policy. Reject an empty result with `unauthorized_capability`. Load a grant by
  ID and hash through a port; missing, expired, hash-mismatched, over-budget, or
  non-narrowing grants return their distinct stable codes.

- [ ] **Step 4: Split eligibility from ranking**

  `EligibilityFilter` checks declared capability, tenant, active status,
  quarantine/suspension, trust floor, and sandbox preflight. Change the existing
  router so its production entry accepts an already eligible tuple and has no
  authority to broaden the capability or select fallback. The Routing Kernel in
  Task 6 may consider `llm_chat` fallback only when the policy marks it inside
  the resolved domain and caller constraints do not exclude it.

- [ ] **Step 5: Run focused tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_routing_authorization.py \
    src/tests/test_routing_eligibility.py \
    src/tests/test_hebbian_router.py
  git add src/routing/authorization.py src/routing/eligibility.py \
    src/integration/hebbian_router.py src/tests/test_routing_authorization.py \
    src/tests/test_routing_eligibility.py src/tests/test_hebbian_router.py
  git commit -m "feat(routing): gate eligibility before Hebbian ranking"
  ```

---

### Task 5: Add the Authstructure verifier port without a production bypass

**Files:**
- Create: `src/auth/verifier.py`
- Create: `src/auth/authstructure.py`
- Create: `src/auth/config.py`
- Create: `src/tests/test_auth_verifier.py`
- Create: `src/tests/fakes/__init__.py`
- Create: `src/tests/fakes/auth.py`
- Modify: `.env.example`
- Modify: `setup_secrets.sh`

**Interfaces:**
- Consumes: raw transport proof only inside `AuthenticationRequest`; the future Authstructure public verification endpoint and signed receipt.
- Produces: `AuthVerifier.verify(request) -> AuthReceiptV1`, `AuthorityContextFactory.root(receipt) -> AuthorityContextV1`, and fail-closed `load_auth_verifier(environment)`.

- [ ] **Step 1: Write failing verifier and factory tests**

  Cover unavailable configuration, malformed signature metadata, receipt hash
  mismatch, wrong audience, expired principal, and successful root authority.
  Assert `repr(AuthenticationRequest)` and every raised error omit the raw
  authorization header and body.

  ```python
  def test_missing_production_verifier_fails_closed(monkeypatch):
      monkeypatch.delenv("ARTEMIS_AUTHSTRUCTURE_URL", raising=False)
      with pytest.raises(AuthConfigurationError) as denied:
          load_auth_verifier("prod")
      assert denied.value.code == "auth_verifier_unavailable"


  def test_root_authority_requires_authenticated_receipt(factory, rejected_receipt):
      with pytest.raises(AuthenticationDenied) as denied:
          factory.root(rejected_receipt)
      assert denied.value.code == "authentication_rejected"
  ```

- [ ] **Step 2: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_auth_verifier.py -q
  ```

  Expected: collection fails because the verifier modules do not exist.

- [ ] **Step 3: Implement the secret-bearing request and verifier protocol**

  Use a frozen dataclass with `repr=False` for the only secret-bearing request:

  ```python
  @dataclass(frozen=True, repr=False)
  class AuthenticationRequest:
      transport: Literal["http", "stdio", "cli"]
      request_id: str
      method: str
      authority: str
      raw_target: bytes
      headers: Mapping[str, tuple[str, ...]] = field(repr=False)
      body: bytes = field(repr=False)


  class AuthVerifier(Protocol):
      def verify(self, request: AuthenticationRequest) -> AuthReceiptV1:
          """Return a verified credential-free receipt or raise a safe denial."""
  ```

  `AuthstructureVerifier` validates contract version, canonical bytes and
  SHA-256, signer namespace/key, audience, receipt time, and principal expiry.
  Do not import Oracle Go `internal` packages. Until the external endpoint is
  published, `load_auth_verifier()` returns no permissive implementation and
  production startup fails with `auth_verifier_unavailable`.

- [ ] **Step 4: Keep test authentication dependency-injected**

  Put `FakeAuthVerifier` in `src/tests/fakes/auth.py`, not production source.
  Delete or quarantine `StaticBearerTokenVerifier` when MCP is converted in
  Task 7. Local CLI/stdio production configuration must use a verifier-issued
  local service receipt; environment strings cannot mint capabilities.

- [ ] **Step 5: Classify environment values without generating provider credentials**

  Add only public/configuration fields to `.env.example`:

  ```dotenv
  ARTEMIS_AUTHSTRUCTURE_URL=
  ARTEMIS_AUTHSTRUCTURE_AUDIENCE=artemis-city
  ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE=
  ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID=
  ```

  `setup_secrets.sh` validates/preserves these operator-supplied values; it does
  not invent a URL, signer namespace, or receipt key. Keep owned local secrets
  under the existing generation/rotation rules.

- [ ] **Step 6: Run tests, secret scan, and commit**

  ```bash
  .venv/bin/python -m pytest src/tests/test_auth_verifier.py -q
  .venv/bin/python -m bandit -q -r src/auth
  ./setup_secrets.sh --check
  git add src/auth/verifier.py src/auth/authstructure.py src/auth/config.py \
    src/tests/test_auth_verifier.py src/tests/fakes/auth.py .env.example \
    setup_secrets.sh
  git commit -m "feat(auth): add fail-closed Authstructure verifier port"
  ```

---

### Task 6: Implement one shared Routing Kernel lifecycle

**Files:**
- Create: `src/routing/kernel.py`
- Create: `src/routing/ports.py`
- Create: `src/tests/test_routing_kernel.py`

**Interfaces:**
- Consumes: intent resolver, authorizer, eligibility filter, ranker, sandboxed executor, and finalizer ports.
- Produces: `RoutingKernel.execute(envelope) -> OutcomeV1`, `RoutingKernel.stream(envelope) -> Iterator[KernelEventV1]`, and `RoutingKernel.preview(envelope) -> RoutingDecisionV1`.

- [ ] **Step 1: Write a recording-port lifecycle harness**

  Build fakes that append exact names to one list. Assert the non-stream trace:

  ```python
  assert trace == [
      "resolve_intent",
      "authorize",
      "filter_eligibility",
      "rank",
      "sandbox_preflight",
      "dispatch",
      "persist_outcome",
      "persist_result_provenance",
      "transition_state",
      "apply_learning_once",
      "enqueue_projections",
  ]
  ```

  Add denial tests asserting no later call occurs after auth, intent,
  authorization, eligibility, or sandbox failure. Add a pinned-agent case and a
  fallback case constrained to the authorized domain.

- [ ] **Step 2: Write sync/stream parity tests**

  Execute identical envelopes through both methods. Ignore `token` projection
  events and assert identical pre-terminal trace, `outcome_id`, `task_id`,
  `routing_decision_id`, and result provenance ID. Assert no `complete` event is
  emitted before finalization returns.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_routing_kernel.py -q
  ```

  Expected: collection fails because `src.routing.kernel` does not exist.

- [ ] **Step 4: Implement shared preparation, dispatch, and finalization**

  Use one private generator as the lifecycle source:

  ```python
  def _run(self, envelope: TaskEnvelopeV1) -> Iterator[KernelEventV1]:
      resolved = self._intent.resolve_envelope(envelope)
      authorized = self._authorizer.authorize(
          envelope.authority,
          resolved,
          envelope.requested_constraints,
      )
      candidates = self._eligibility.candidates(authorized)
      decision = self._ranker.rank(authorized, candidates)
      self._sandbox.preflight(decision, authorized)
      yield KernelEventV1.routing(envelope, decision)
      result = yield from self._executor.dispatch(envelope, decision)
      outcome = self._finalizer.finalize(envelope, decision, result)
      yield KernelEventV1.complete(outcome)
  ```

  `execute()` drains `_run()` and returns the terminal outcome. `stream()`
  yields `_run()` directly. `preview()` stops before dispatch and cannot mutate
  memory, provenance, learning, or the task ledger. The durable implementation
  of `finalize()` lands in the task-ledger plan; use a recording port here.

- [ ] **Step 5: Run focused kernel and routing tests**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_auth_contracts.py \
    src/tests/test_auth_verifier.py \
    src/tests/test_routing_contracts.py \
    src/tests/test_routing_intent.py \
    src/tests/test_routing_authorization.py \
    src/tests/test_routing_eligibility.py \
    src/tests/test_routing_kernel.py \
    src/tests/test_hebbian_router.py
  ```

  Expected: all focused tests pass.

- [ ] **Step 6: Commit the kernel lifecycle**

  ```bash
  git add src/routing/kernel.py src/routing/ports.py \
    src/tests/test_routing_kernel.py
  git commit -m "feat(routing): add one shared execution lifecycle"
  ```

---

### Task 7: Reduce MCP common to a declared adapter over the canonical core

**Files:**
- Modify: `services/mcp/common/pyproject.toml`
- Modify: `services/mcp/common/src/artemis_mcp_common/__init__.py`
- Modify: `services/mcp/common/src/artemis_mcp_common/models.py`
- Delete: `services/mcp/common/src/artemis_mcp_common/gate.py`
- Delete: `services/mcp/common/src/artemis_mcp_common/principals.py`
- Modify: `services/mcp/common/tests/test_models.py`
- Replace: `services/mcp/common/tests/test_gate.py`
- Modify: `docs/superpowers/plans/2026-08-16-artemis-mcp-foundation-memory-server.md`

**Interfaces:**
- Consumes: installed `artemis-city` contracts, `AuthVerifier`, and `RoutingKernel`.
- Produces: MCP transport DTOs and an adapter that rejects authority-bearing input and delegates exactly once.

- [ ] **Step 1: Add failing anti-authority adapter tests**

  Assert an MCP tool payload containing `principal`, `authority`,
  `delegation`, or `required_capability` as an authorization decision is
  rejected. Assert the adapter obtains authority from the injected verifier and
  calls one injected kernel method exactly once.

- [ ] **Step 2: Prove the current nested package is not independently installable**

  Run from the repository root without `PYTHONPATH` injection:

  ```bash
  .venv/bin/python -m pytest services/mcp/common/tests -q
  ```

  Expected before the fix: collection fails with
  `ModuleNotFoundError: artemis_mcp_common` or an undeclared `src` dependency.
  Record this as the baseline; do not normalize it away with source-path
  injection.

- [ ] **Step 3: Remove the competing gate and static verifier**

  Delete `GovernedGate`, `ServicePrincipal`, `GovernedContext`, local
  environment capability minting, and the production static bearer verifier.
  Keep only strict credential-free transport DTOs that import canonical models
  from the installed Artemis package. Declare the root package dependency and
  configure isolated package tests so installation—not `PYTHONPATH`—resolves
  imports.

- [ ] **Step 4: Mark the superseded plan steps explicitly**

  At the top of the MCP foundation plan, add a warning that its original Tasks
  2 and 3 are superseded by this plan and must not be used as an authorization
  authority. Preserve the historical task text for auditability.

- [ ] **Step 5: Build and test the adapter in isolation**

  ```bash
  .venv/bin/python -m build --wheel
  .venv/bin/python -m pip install --no-deps --target /private/tmp/artemis-wheel-test \
    dist/artemis_city-*.whl
  cd services/mcp/common
  ../../../.venv/bin/python -m build --wheel
  ../../../.venv/bin/python -m pytest tests -q
  ```

  Expected: both wheels build, common tests pass without source-path injection,
  and the common wheel contains no authentication or routing authority.

- [ ] **Step 6: Commit the MCP boundary correction**

  ```bash
  git add services/mcp/common/pyproject.toml \
    services/mcp/common/src/artemis_mcp_common/__init__.py \
    services/mcp/common/src/artemis_mcp_common/models.py \
    services/mcp/common/src/artemis_mcp_common/gate.py \
    services/mcp/common/src/artemis_mcp_common/principals.py \
    services/mcp/common/tests/test_models.py \
    services/mcp/common/tests/test_gate.py \
    docs/superpowers/plans/2026-08-16-artemis-mcp-foundation-memory-server.md
  git commit -m "refactor(mcp): delegate governance to Routing Kernel"
  ```

---

### Task 8: Run the governed-core review gate

**Files:**
- Inspect: all files named by Tasks 1-7.
- Modify only when a focused check identifies a regression in those files.

**Interfaces:**
- Consumes: completed governed core.
- Produces: a reviewable green core before task-ledger or ingress wiring begins.

- [ ] **Step 1: Run canonical focused tests**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_auth_contracts.py \
    src/tests/test_auth_verifier.py \
    src/tests/test_routing_contracts.py \
    src/tests/test_routing_intent.py \
    src/tests/test_routing_authorization.py \
    src/tests/test_routing_eligibility.py \
    src/tests/test_routing_kernel.py \
    src/tests/test_atp_context.py \
    src/tests/test_atp_validator.py \
    src/tests/test_hebbian_router.py
  ```

- [ ] **Step 2: Run touched-code quality checks**

  ```bash
  .venv/bin/python -m black --check src/auth src/routing \
    src/tests/test_auth_contracts.py src/tests/test_auth_verifier.py \
    src/tests/test_routing_contracts.py src/tests/test_routing_intent.py \
    src/tests/test_routing_authorization.py src/tests/test_routing_eligibility.py \
    src/tests/test_routing_kernel.py
  .venv/bin/python -m ruff check src/auth src/routing --no-cache
  .venv/bin/python -m mypy src/auth src/routing
  ```

- [ ] **Step 3: Review for authority duplication and secret leakage**

  ```bash
  grep -RInE "GovernedGate|ServicePrincipal|StaticBearerTokenVerifier" \
    src services/mcp/common/src
  grep -RInE "FASTAPI_API_KEY|MCP_API_KEY|Authorization" \
    src/auth src/routing services/mcp/common/src
  ```

  Expected: no competing gate/principal implementation; any `Authorization`
  mention is confined to the non-serializable transport request and no raw
  secret is logged, returned, persisted, or embedded in a model.

- [ ] **Step 4: Request independent review before wiring an ingress**

  The reviewer must explicitly verify authentication-before-ATP order,
  authority intersection, strict/non-downgradeable ATP, eligibility-before-
  ranking, sync/stream parity, and absence of production authentication bypass.
