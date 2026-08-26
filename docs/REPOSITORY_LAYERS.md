# Repository Layers

This guide maps every maintained Artemis City runtime layer to its source of
truth, public boundary, durable state, and validation surface. It is the
repository-level orientation guide; detailed algorithms and wire contracts stay
in the linked authoritative documents.

## End-to-end request path

```text
CLI / FastAPI / Express / trusted in-process caller
                    |
                    v
        Authentication and authority
                    |
                    v
          ATP validation and intent
                    |
                    v
  Authorization -> eligibility -> learned ranking
                    |
                    v
       Orchestrator and agent execution
                    |
                    v
    Governance, learning, memory, provenance
                    |
                    v
       HTTP / CLI / UI response adapters
```

The order is load-bearing. Authentication does not authorize a route, ATP does
not grant a capability, and learned scores cannot rescue an agent rejected by
policy, trust, quarantine, or sandbox admission.

## 1. Ingress and presentation

| Surface | Source | Contract | Notes |
|---|---|---|---|
| Canonical CLI | `src/launch/main.py` | `make run`, task and inspection flags | Builds trusted typed input and delegates to the Python core. |
| FastAPI dashboard | `app/api/main.py` | `/api/*` | Serves the React dashboard and can expose an explicit read-only SQLite fallback when orchestration imports fail. |
| TypeScript Express API | `app/api/index.ts`, `app/api/v1/` | `/api/v1/*` | Public versioned HTTP boundary. Python-owned behavior crosses only `app/api/lib/pythonBridge.ts`. |
| React dashboard | `app/web/frontend/src/` | Browser UI, `/api/*` client | Vite proxies to FastAPI on port 8000; it does not call Express implicitly. |
| JSON bridge | `src/api_bridge.py` | One JSON request and response envelope over stdin/stdout | Keeps Python as the domain source of truth. Stdout belongs exclusively to the protocol. |

Ingress adapters own transport parsing, authentication handoff, and response
translation. They do not own routing, trust, memory consistency, or provider
fallback policy.

Tests: `src/tests/test_api_bridge.py`, `src/tests/test_api_main.py`, and
`app/api/__tests__/`.

## 2. Authentication and authority

Source: `src/auth/`.

This layer converts transient request proof into immutable, credential-free
evidence. Its contracts distinguish identity, verified scopes, receipt
provenance, acting party, requester, and optional delegation.

- `contracts.py` defines strict frozen Pydantic records and recursively rejects
  credential-bearing fields.
- `verifier.py` defines the transport-neutral verifier port, safe denial codes,
  and root authority factory.
- `authstructure.py` validates canonical Authstructure receipt artifacts without
  returning or retaining bearer proof.
- `delegation.py` defines hashed, bounded, persisted child grants.
- `config.py` intentionally fails closed until the external Authstructure
  verifier contract is enabled and conformant.

Authentication proves who and what scopes were verified. Artemis authorization
still decides whether those scopes permit the requested mode, action,
capability, target zone, and delegation.

Tests: `src/tests/test_auth_contracts.py` and
`src/tests/test_auth_verifier.py`.

## 3. ATP validation and intent resolution

Sources: `src/validation/`, `src/agents/atp/`, and `src/routing/intent.py`.

`ATPValidationService` is the transport-neutral parse, validate, and format
boundary. It wraps the canonical ATP parser and validator and returns frozen,
typed reports with stable issue codes. `services/mcp/artemis-validation/`
registers it as a read-only, authenticated, stdio-only MCP transport over the
official SDK.

Routing intent resolution accepts exactly one of two sources:

1. strict caller ATP; or
2. an explicit `TaskIntentV1` from a trusted typed adapter.

The reviewed `(Mode, ActionType)` domain is pinned by code and policy. A caller
constraint may narrow that domain but cannot expand it. See
[`API_REFERENCE.md`](API_REFERENCE.md) for ATP syntax and
[`CODING_STANDARDS.md`](CODING_STANDARDS.md) for fail-closed invariants.

Tests: `src/tests/test_atp_validation_models.py`,
`src/tests/test_atp_validation_service.py`, and
`src/tests/test_routing_intent.py`.

## 4. Routing and authorization

Source: `src/routing/`, with live adapters in `src/routing/adapters.py`.

`RoutingKernel` is the single in-process routing entry point. Its stages run in
this order:

```text
IntentResolver -> ArtemisAuthorizer -> EligibilityFilter -> HebbianRanker
```

- `ArtemisAuthorizer` intersects verified requester and actor scopes,
  delegation, resolved intent, caller constraints, target-zone policy, and the
  Artemis capability policy.
- `EligibilityFilter` removes inactive, quarantined, below-trust-floor, or
  sandbox-ineligible agents.
- `HebbianRanker` ranks only the surviving candidates using registry,
  learned-history, and optional trust signals.
- `delegation_store.py` persists immutable grants and budget reservations.

The policy files under `config/routing/` are reviewed inputs, not an unrestricted
extension mechanism. The code-pinned reviewed domain must also change before a
new ATP execution pair becomes routable.

Tests: `src/tests/test_routing_*.py`.

## 5. Orchestration and agent execution

Sources: `src/mcp/orchestrator.py` and `src/agents/`.

The orchestrator owns the execution lifecycle after ingress:

- route exactly once through `route_task`;
- dispatch through registry and sandbox boundaries;
- preserve parent/child provenance;
- classify provider availability separately from agent quality;
- persist reports and memory outcomes; and
- apply learning only to eligible measured outcomes.

Agent implementations own capability-specific work. `LLMAgent` records redacted
Exo wire evidence. Provider failures do not emit substitute model text, and a
local baseline is used only when explicitly enabled and labelled degraded.

Long provider output is stored as an exact non-embedded artifact before a
governed `text_summarization` child is routed for follow-on context.

Tests: orchestrator, agent, provider, streaming, and context-compression tests
under `src/tests/`.

## 6. Registry, governance, and learning

Sources: `src/integration/agent_registry.py`, `src/governance/`,
`src/integration/sandbox.py`, `src/integration/trust_interface.py`, and
`src/integration/hebbian_router.py`.

| Concern | Owner | Durable state |
|---|---|---|
| Agent inventory and composite scores | Agent registry | `data/agent_registry.db` |
| Learned agent-to-scope and pair signals | Hebbian layer | `data/hebbian_weights.db` |
| Trust levels and decay | Trust interface/governance | Registry projections and governance records |
| Tool/path/operation enforcement | Agent sandbox | Violations and quarantine state |
| Approval and rollback | Governance modules | Checkpoints and governance events |

Provider availability, cancellation, and explicitly degraded execution remain
observable but learning-ineligible. Genuine measured agent failures may update
trust and Hebbian state. Sentinel signals are observational and do not change
ranking or quarantine by themselves.

## 7. Memory and projections

Sources: `src/integration/memory_bus.py`,
`src/integration/sql_memory_store.py`, `src/memory/`,
`src/mcp/vector_store.py`, and `src/obsidian_integration/`.

In explicit PostgreSQL or Neon mode, SQL is canonical. A write commits an
immutable revision, current head, and projection outbox event atomically.
Vector and Obsidian projections are derived and may remain pending without
discarding the canonical commit. Legacy mode retains the historical vault-backed
bus as a reversible rollout path.

`src/obsidian_integration/manager.py` constrains all vault operations to
validated relative paths and uses safe file replacement. Parsers and generators
translate between typed tasks/results and human-readable Markdown; they do not
own canonical SQL identity or revision ordering.

Detailed guarantees: [`MEMORY_BUS.md`](MEMORY_BUS.md).

## 8. Observability and operations

Sources: `src/integration/run_logger.py`, `src/utils/`, `monitoring/`,
`config/environments/`, and the root `Makefile`.

- `data/run_logs.db` links routing, execution, memory, learning, and completion
  through parent/child provenance identifiers.
- `logs/` contains human-readable diagnostics; request-derived text is
  normalized before logging and credentials must never appear.
- `src/runtime_paths.py` resolves repo-stable data and log roots, with explicit
  environment overrides for deployment and tests.
- GitHub Actions owns source, test, security, lineage, protected live, and
  `dev -> staging -> prod` promotion gates. No CircleCI config is present.

Operational commands and environment ownership are documented in
[`DEPLOYMENT.md`](DEPLOYMENT.md), [`ENVIRONMENTS.md`](ENVIRONMENTS.md), and
[`CICD.md`](CICD.md).

## Transitional and non-authoritative surfaces

| Path | Status |
|---|---|
| `app/kernel/` | Packaged in-process kernel layer that is growing toward orchestrator parity; it does not replace the shared Routing Kernel contract. |
| `Concept_Demos/` | Supported prototypes, not production sources of truth. |
| `src/Artemis Agentic Memory Layer/` | Standalone Obsidian REST shell (`make server`). Not registered in the root workspace, and not a Model Context Protocol implementation despite its name. |
| `services/mcp/` | Real Model Context Protocol servers on the official `mcp[cli]` SDK, adapting `src/` domain services. `artemis-validation` and `artemis-memory` are implemented; `common` is quarantined pending review. |
| `src/Kernel/`, root `memory/`, and root `tests/` | Compatibility or migration copies; follow `PROJECT_BOUNDARIES.md` before editing. |

## Documentation and docstrings

- README owns identity, the top-level map, quick start, and current feature
  summary.
- This guide owns the repository layer map.
- Architecture, memory, API, governance, deployment, and testing details stay in
  their named authoritative documents.
- Maintained Python modules describe responsibility and important side effects
  in module docstrings.
- Public contracts and non-obvious domain behavior use Google-style docstrings.
  Annotations remain the source of type information, so docstrings should not
  repeat obvious signatures.
- Generated, vendored, archived, test-only, and reverse-sync-held files are not
  rewritten solely to improve docstring counts.

The generated API view for the new authority and ATP contracts is available in
[`PYTHON_API.md`](PYTHON_API.md).
