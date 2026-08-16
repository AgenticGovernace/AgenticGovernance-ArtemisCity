# Artemis MCP Backend Servers Design

**Date:** 2026-08-16

**Status:** Accepted implementation direction

## Purpose

Turn the useful intent in `/Users/pucci/projects/prove/tool-servers` into
production Artemis City MCP servers while keeping Artemis City's Python core
authoritative. Use `/Users/pucci/projects/servers` as the local MCP SDK
conformance reference, not as a destination or a production dependency.

This design also incorporates the 2026-08-16 routing feedback: the blend is a
convex combination, failure evidence is attributed by layer, and unknown
failures increase uncertainty and accelerate evidence decay rather than
inventing model or provider blame.

## Evidence and constraints

- The six Prove tool-server directories are prototypes. Several current
  modules do not import or expose tools, and their copied provenance helpers
  have diverged. Their tool names and domain intent are reference material;
  their runtime and persistence code are not copied.
- Prove's root `provenance_core.py` plus `provenance_mcp.py` is the reusable
  architectural example: one transport-independent core, typed MCP outputs,
  stdio and Streamable HTTP, and real-client contract tests.
- `/Users/pucci/projects/servers` is the official reference-server monorepo.
  It supplies packaging, schema, annotation, transport, resource, and testing
  patterns. It explicitly does not supply Artemis auth, ATP, provenance,
  tenancy, routing, or storage policy.
- Artemis City's canonical runtime logic remains under `src/`. MCP, HTTP,
  bridge, and CLI code adapt that core and do not reimplement it.
- Existing worktree changes are preserved. New server work uses new paths and
  only narrowly changes canonical modules behind regression tests.

## Repository layout

Each MCP server is independently buildable while remaining co-versioned with
the Artemis City core:

```text
services/mcp/
  common/
    pyproject.toml
    src/artemis_mcp_common/
    tests/
  artemis-memory/
    pyproject.toml
    src/artemis_memory_mcp/
    tests/
  artemis-provenance/
  artemis-task/
  artemis-registry/
  artemis-governance/
  artemis-validation/
  artemis-routing/
```

Domain services and ports live with the authoritative Python core:

```text
src/
  auth/
  memory/
  provenance/
  routing/
  integration/
```

Server packages contain transport setup, MCP input/output models, tool and
resource registration, and dependency wiring only.

## Common governed request pipeline

Every state-changing MCP call follows one ordered pipeline:

```text
authenticate principal
  -> validate ATP strictly
  -> resolve policy-owned capability
  -> authorize principal for capability and scope
  -> execute one canonical Artemis service operation
  -> persist durable outcome
  -> persist completion provenance
  -> perform an eligible learning update, if any
  -> return a typed MCP result
```

No caller-supplied agent, capability, trust value, or learned score may bypass
an earlier gate. Missing auth, ATP, or required provenance configuration fails
closed. Secrets and raw credentials never appear in logs, provenance records,
errors, or browser assets.

Memory namespace is an authorization scope, not merely caller data. Each memory
tool requires the exact `memory:namespace:{namespace}` grant or the explicit
server-recognized `memory:namespace:*` grant in addition to its read/write
capability. Status requests carry both namespace and immutable record ID so a
logical memory ID cannot blur per-version projection state.

Local stdio uses an explicitly configured service principal. Streamable HTTP
uses the shared Artemis principal verifier. The verifier and MCP SDK
`AuthSettings` are both attached to the `MCPServer` constructor so the HTTP
middleware rejects missing or invalid bearer tokens before a tool handler can
run. A server cannot start an HTTP listener in an unauthenticated production
mode.

## MCP conformance contract

- Default local transport: stdio. Application diagnostics use stderr.
- Remote transport: Streamable HTTP at `/mcp`; legacy SSE is not added.
- New tool names are verb-first and kebab-case.
- Authority-bearing inputs are Pydantic models with `extra="forbid"`.
- Decision-driving operations return typed models so `outputSchema` and
  `structuredContent` expose real fields. A human-readable `summary` is part
  of the same result.
- Protocol validation uses typed MCP errors. Expected operation failures are
  not returned as successful prose.
- Every tool declares accurate `readOnlyHint`, `destructiveHint`,
  `idempotentHint`, and `openWorldHint` values.
- Persistent stores expose stable resources only when a resource request can
  carry or resolve the same governed ATP context as a tool call. The initial
  memory server remains tool-only; its URI resource is deferred until a durable
  provenance/ATP reference can be resolved without synthesizing caller intent.
  Notifications occur only after the underlying write commits.
- Contract tests initialize a real MCP client and inspect `tools/list`,
  `inputSchema`, `outputSchema`, runtime `structuredContent`, and one
  representative error.

## Server boundaries

| Server | Prove source intent | Artemis-owned service | Initial surface |
|---|---|---|---|
| `artemis-memory` | memory read/write/search | `MemoryService` | write, read, search, status tools |
| `artemis-provenance` | root provenance MCP | `ProvenanceService` | mint, bind, log, chain, verify |
| `artemis-task` | kernel task operations | orchestrator/task service | submit, get, list, cancel; internal completion |
| `artemis-registry` | agent registry | `AgentRegistry` facade | get/list; governed registration and updates |
| `artemis-governance` | approvals and rollback | governance services | propose, inspect, approve/reject, rollback |
| `artemis-validation` | ATP validator | authoritative ATP validator | parse, validate, format; no EXO proxy or reflection experiments |
| `artemis-routing` | Hebbian diagnostics | routing service | preview and diagnostics; no ungoverned learning mutation |

## Memory write-through contract

Neon-compatible PostgreSQL is the canonical memory ledger. Obsidian and the
vector index are projections.

The provider-neutral `db/migrations/0001_memory_write_through.sql` schema and
`src/integration/sql_memory_store.py` adapter are the starting point. Server
work evolves that schema with a versioned migration and a thin domain adapter;
it does not create incompatible replacement tables under the same names.

One SQL transaction writes:

1. an immutable memory version;
2. the current memory head;
3. one outbox event per requested projection; and
4. a durable memory-write completion-provenance event linked to its parent; and
5. the idempotency binding.

Only after that transaction commits may projection delivery begin. The service
attempts Obsidian and vector projection during the call when configured, then
records each outcome. A projection failure leaves the SQL record committed and
the outbox event retryable. It never deletes the canonical row and never
reports both stores as synchronized.

SQL failure means no Obsidian or vector write. Idempotent replay returns the
original memory version and may retry a still-pending projection without
creating a duplicate version. User-influenced paths are derived from validated
namespace and memory identifiers and checked against the resolved vault root.
Compatibility callers may supply an already validated vault-relative path,
which is preserved exactly.

New writes persist authenticated principal ID, parent provenance ID, and a
ledger-generated child completion-provenance ID exactly once. Historical rows
without that evidence remain explicitly nullable; migration never fabricates
identity or provenance claims. Idempotent replay returns the original child
ID.

Projection delivery is serialized with head advancement for the same logical
memory key. A delivery claim holds the same PostgreSQL advisory lock used by a
write, checks the locked current head, and marks an older event `skipped`
without touching Obsidian or the vector index. This prevents a delayed version
1 retry from overwriting a successfully projected version 2.

The initial local-vault projector is POSIX-only and fails before mutation on
Windows. It holds no-follow directory descriptors from the vault root through
binary UTF-8 temp write, file fsync, descriptor-relative replace, and parent
fsync; a pathname validation followed by later path-based replacement is not a
sufficient confinement guarantee.

A write receipt contains at least:

- logical `memory_id`, immutable `record_id`, `namespace`, and version;
- content SHA-256;
- idempotency key;
- SQL, Obsidian, and vector projection statuses;
- provenance ID and timestamp; and
- a human-readable summary.

## Routing and learning contract

### Blend

The live router's three-signal blend remains a convex combination:

```text
score = (1 - alpha - beta) * composite
      + alpha * hebbian_normalized
      + beta * trust
```

`alpha` and `beta` are in `[0, 1]` and `alpha + beta <= 1`. With trust disabled
(`beta = 0`), this is exactly:

```text
score = (1 - alpha) * composite + alpha * hebbian_normalized
```

Therefore `alpha = 0` equals the composite score. For `alpha = 0.3`,
`composite = 0.5`, and `hebbian_normalized = 1.0`, the score is `0.65`.
The erroneous `1 + alpha` coefficient is not a valid weighting formula and is
not introduced into code or documentation.

### Evidence axes

Routing evidence is not one generic failure counter. It is scoped by:

- model performance;
- provider reliability;
- model-provider route reliability;
- agent/policy execution;
- ATP routing domain;
- corpus, schema, prompt, and policy versions.

Confirmed provider failure updates provider and route evidence, not model
outcome evidence. Confirmed malformed model output updates model and route
evidence, not provider reliability. Confirmed policy block records a governance
event and does not masquerade as model or provider failure.

### Unknown failures

An unknown failure is a completed route error whose validators cannot yet
attribute the cause. It increments route-level error and unresolved counters,
but applies no categorical model, provider, or agent penalty.

Evidence continues to decay. Unresolved pressure shortens the route's effective
half-life:

```text
effective_half_life = base_half_life / (1 + gamma * unresolved_pressure)
lambda_effective = 2 ** (-1 / effective_half_life)
next_weight = lambda_effective * current_weight
```

The base observation window is approximately 69 comparable routing steps.
Validated success by an alternative route adds comparative evidence; it does
not retroactively invent a cause for the failed route.

Routing probabilities and normalized entropy are diagnostic inputs to Sentinel.
Sentinel may request rerouting or governance review when entropy, unresolved
pressure, and stability thresholds jointly cross policy limits. Quarantine is
a governed state transition with durable evidence, not an automatic side effect
of one timeout or the mere passage of a half-life.

No learning update occurs until the outcome and its provenance are durable and
the failure classification is eligible.

## Migration and reverse-sync policy

- Prove and Oracle remain evidence/reference repositories. Production server
  code is not reverse-synced back into them automatically.
- Only canonical files named by a reviewed manifest may participate in reverse
  sync. Environments, locks from unrelated runtimes, logs, databases, caches,
  conflict copies, and generated artifacts are excluded.
- The orphan TypeScript `src/mcp-server/` REST shell is not extended as MCP.
  Existing public HTTP controllers remain stable while they migrate to the same
  Python services used by MCP.
- `src/integration/memory_bus.py` keeps its public compatibility surface while
  delegating writes to `MemoryService` after the new service is proven.

## Implementation sequence

1. Lock the corrected routing blend with a literal numeric regression test.
2. Add the common MCP contract package and real-client schema harness.
3. Implement the PostgreSQL memory ledger/outbox and projection ports.
4. Implement `MemoryService` and compatibility adapter tests.
5. Ship and verify `artemis-memory` over stdio and Streamable HTTP.
6. Extract provenance using the proven Prove shared-core pattern.
7. Add task, registry, governance, and validation servers as thin adapters.
8. Add the read-only routing server and then the attributed-failure/entropy
   state model behind dedicated routing tests.

Each step must preserve existing behavior, distinguish baseline failures from
regressions, and pass the repository's coding, security, and contract gates.
