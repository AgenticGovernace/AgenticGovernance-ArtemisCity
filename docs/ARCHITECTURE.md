# Artemis City Architecture

## Overview

Artemis City is a multi-agent operating system designed for autonomous task
orchestration with adaptive learning and governance. The system combines
credential-free authority evidence, strict ATP intent resolution, distributed
task routing, semantic memory persistence, Hebbian learning, and sandbox-based
security into a cohesive framework. See
[`REPOSITORY_LAYERS.md`](REPOSITORY_LAYERS.md) for the source, state, tests, and
ownership boundary of every maintained runtime layer.

## Request-layer invariants

Every governed execution follows the same conceptual order:

```text
Ingress -> Authentication -> ATP/typed intent -> Authorization
        -> Eligibility -> Learned ranking -> Execution
        -> Persistence/learning/provenance -> Response
```

- Authentication produces credential-free evidence; Artemis alone authorizes
  capabilities and operations.
- Strict ATP or a trusted typed adapter establishes the routing domain before a
  learned score is consulted.
- Authorization and eligibility can only narrow candidates. Quarantine, trust,
  and sandbox decisions occur before learned ranking.
- Provider availability and agent quality are classified separately so an
  infrastructure failure cannot train agent trust or Hebbian weights.
- Canonical state commits before derived projections are reported as complete.

The public Authstructure integration remains deliberately fail-closed until a
conforming external verifier contract is enabled. Trusted local callers present
an explicit, auditable system authority rather than bypassing the Routing
Kernel.

## Core Components

### 1. Kernel (Task Router)

The Kernel is the central task dispatcher and orchestrator.

**Responsibilities:**

- Receives incoming tasks and requests
- Queries Agent Registry for candidates matching task requirements
- Ranks agents by Hebbian-weighted capability scores
- Routes tasks to the optimal agent
- Manages task execution lifecycle and error handling
  **Scoring Algorithm:**

```
Composite = (Alignment × 0.4) + (Accuracy × 0.4) + (Efficiency × 0.2)
Rank = ((1 - alpha - beta) × Composite)
     + (alpha × NormalizedHebbianWeight)
     + (beta × Trust)
```

**Key Behaviors:**

- Fallback routing if primary agent unavailable
- Load balancing across agents with similar scores
- Separate provider connect/read deadlines: connections fail quickly while an
  accepted Exo generation may run for 15 minutes by default (or without a read
  deadline when explicitly configured)
- Bounded retry/backoff for connect failures and Exo 429/502/503/504 responses;
  read timeouts and partially emitted streams are never replayed

### 2. Memory Bus

The Memory Bus coordinates canonical SQL memory, a human-readable Obsidian
projection, and a derived semantic vector index. In the default `legacy` mode,
the established vault-backed bus remains available for a reversible rollout.
When an operator explicitly selects `postgres` or `neon`, PostgreSQL is the
source of truth; invalid SQL configuration fails closed rather than silently
using the legacy store.

**Architecture:**

```
┌─────────────────────────────────────────┐
│          Kernel / Agents                │
└────────────────┬────────────────────────┘
                 │ Read/Write
       ┌─────────▼─────────┐
       │   Memory Bus      │
       │  (Coordinator)    │
       └───┬─────────┬────────┘
           │         │
     ┌─────▼───┐ ┌───▼──────┐
     │PostgreSQL│ │ Vector   │
     │ledger +  │ │ index    │
     │outbox    │ └──────────┘
     └─────┬───┘
           │
     ┌─────▼─────┐
     │ Obsidian  │
     │ projection│
     └───────────┘
```

**Read Hierarchy:**

1. **Exact Match in SQL mode**: the committed current head is authoritative,
   including while an Obsidian projection is pending. The bridge constructs
   neither local projection to serve this exact read.
2. **SQL-mode semantic search**: an optional exact SQL path is followed by
   vector similarity from the derived index. SQL mode does not keyword-scan the
   Obsidian projection, so vector-pending or `embed=False` records require an
   exact path.
3. **Legacy mode**: the established vault keyword and vector fallback remains
   available only when the SQL ledger is not selected.

**Write protocol:** the bus validates the request, commits an immutable SQL
revision/current head/Obsidian outbox event in one transaction, then holds the
writer-compatible PostgreSQL advisory path fence while classifying and updating
the vector and deterministic Obsidian projections. Projection adapters are
lazy: writes reach the SQL commit before their first construction attempt. A
post-commit vector failure
returns `accepted` with `vector_status=pending` and does not attempt Obsidian.
A failed or unacknowledged Obsidian projection likewise returns `accepted` with
`sync_pending=true`; neither case deletes the committed revision or turns the
result into an Obsidian-only success. This first slice has no background
projector or automatic retry. Calls without a key receive a new UUID operation
key, so repeated content creates a new revision; callers get retry semantics by
explicitly reusing one key. Full outcome and replay details are in
`docs/MEMORY_BUS.md`.

### 3. Hebbian Learning Layer

Adaptive connection strength between agents and task types through Hebbian weighting.

**Mechanism:**

- Weight matrix: Agent × Task Type
- Initial weight: 1.0
- Success: `ΔW = tanh(learning_rate × normalized_performance)`
- Failure: anti-Hebbian `ΔW = -learning_rate`
- Per-outcome decay: `W = max(0.01, (W + ΔW) × 0.99)`
- Sequential pair weights capture agent hand-off synergy
- Rolling 30-run timing/performance signals warm up after 5 samples
- Routing intelligence compounds individual entropy, positive pair value,
  and timing-score diversity
  **Storage Backend:**
- SQLite-backed persistence in `data/hebbian_weights.db`
- Atomic updates via transactions
- A learning-event row is written for every measured agent outcome. Provider
  availability failures and explicitly degraded local baselines are recorded in
  provenance but do not change Hebbian weights or trust.
- Current Hebbian, execution, timing, and trust summaries are mirrored into
  `data/agent_registry.db`

### 4. Agent Registry

Central inventory of all agents and their capabilities.

**Registration Record:**

```json
{
  "agent_id": "uuid",
  "name": "string",
  "capabilities": ["string"],
  "alignment_score": 0.0-1.0,
  "accuracy_score": 0.0-1.0,
  "efficiency_score": 0.0-1.0,
  "status": "active|suspended|quarantined",
  "trust_tier": "auto|monitored|human",
  "last_updated": "iso8601"
}
```

**Capabilities Matching:**

- Tag-based (e.g., "text-generation", "code-analysis")
- Semantic similarity to task requirements
- Version constraints (agents with capability v2+)
  **Scoring:**
- Alignment: Consistency with system values and user intent
- Accuracy: Correctness of outputs (sampled validation)
- Efficiency: Resource usage and latency
- All scores updated post-execution

### 5. Sandbox System

Per-agent security isolation with tool whitelisting and permission checks.

**Enforcement Layers:**

1. **Tool Whitelist**: Agent has pre-approved list of callable tools
2. **File Permissions**: Path-based ACL with read/write restrictions
3. **Network Controls**: Domain/port allowlists, rate limiting
4. **Violation Logging**: All attempts logged to audit trail
   **Quarantine Rules:**

- Auto-quarantine after 3 policy violations
- Manual override by trust tier
- Quarantine status queryable in Agent Registry
- Rollback to last known good state on violation

### 6. Governance Framework

Multi-tier approval workflow for self-updates and policy changes.

**Update Tier:**

- **Auto**: Low-risk patches (<1% code change, fully backwards-compatible)
- **Monitored**: Standard updates (human approval + automated testing)
- **Human**: Major versions, policy changes, capability additions
  **Workflow:**

1. Update proposed with metadata (tier, risk score, rollback point)
2. Automated testing (unit, integration, security)
3. Conditional approval based on tier (auto-approved vs. queued)
4. Atomic deployment with checkpoint
5. Rollback available for 30 days post-deployment

## System Data Flow

```
┌──────────────────┐
│ External Request │
└────────┬─────────┘
         │
    ┌────▼──────────────────┐
    │  Kernel (Routing)     │
    │  - Parse task         │
    │  - Query Registry     │
    │  - Filter on trust    │
    │    floor + governance │
    │  - Rank by blend of   │
    │    composite +        │
    │    Hebbian + trust    │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Sandbox Check        │
    │  - Verify permissions │
    │  - Whitelist tools    │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Execute on Agent     │
    │  - Run task           │
    │  - Log telemetry      │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Hebbian Update       │
    │  - tanh/anti-Hebbian  │
    │  - decay + pair/time  │
    │  - registry + trust   │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Memory Persistence   │
    │  - Commit SQL ledger  │
    │  - Queue projections  │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Return Result        │
    │  (incl. RoutingDecision: │
    │   chosen agent +      │
    │   per-candidate       │
    │   blended scores)     │
    └───────────────────────┘
```

The Hebbian routing decision is not just an internal scoring step — it
is captured by the FastAPI executor (`POST /api/cli/execute`) and
returned to the caller as the `agent_name` and `routing` fields on
`ExecuteInstructionResponse`. The dashboard Executor page renders the
per-candidate blended-score breakdown so operators can observe how the
router weighted composite score, scoped Hebbian history, pair/timing signals,
and trust for each capability match. ATP action types create distinct learning
scopes (`atp:<action>:<capability>`) while still filtering agents by their real
capabilities. This lets Summarize, Execute, and Reflect develop separate
associations without inventing duplicate agent identities. The blend is
`(1 - α - β)·composite + α·hebbian_norm + β·trust`; agents below
`trust_floor` are excluded before scoring. See the "Dashboard executor
contract" section of `CLAUDE.md` for the response shape and the
controlling env vars.

Every routed prompt has one parent provenance ID in `data/run_logs.db`.
Routing, sandbox dispatch, memory persistence, Hebbian/trust learning, and
completion are child events, making one execution reconstructable without
joining on log text. ATP tasks fail closed when the provenance sink is not
available.

The Hebbian sentinel calculates rolling success/failure sign changes per
agent and routing scope. It stores current state and alert transitions in
`data/hebbian_weights.db`, mirrors the current signal into the agent registry,
and exposes it through both API boundaries. It is deliberately observational:
the signal appears in routing diagnostics but is not part of the blended score
and cannot autonomously modify weights, trust, or quarantine state.

### Verified Exo execution and context compression

LLM success is backed by wire evidence, not a controller-generated response.
`LLMAgent` records the concrete endpoint, HTTP status, stable request ID, Exo
response/model IDs, latency, attempt history, token usage, output length, and
SHA-256. The Express `/api/v1/llm/chat` and `/complete` routes cross the JSON
bridge into this Python implementation; unsupported demo-era LLM operations
return `501` instead of synthetic data.

When successful Exo text crosses `ARTEMIS_EXO_SUMMARY_THRESHOLD_CHARS`, the
orchestrator keeps the complete output as a non-embedded raw artifact and
routes a governed child task over the `text_summarization` capability. The
requesting agent and chosen summarizer receive independent copies of the same
memory-enriched source context. The child uses the dedicated
`system:context_compression:text_summarization` scope, so summarizers compete
with their own Hebbian history. The terminal result contains compressed
follow-on context plus the raw artifact path/hash and child routing decision.
Raw text is removed from the response only after either the raw artifact or the
consumer report was durably written.

## Integration Points

**Obsidian Integration:**

- Renders deterministic full-file projections from committed SQL revisions
- Receives idempotent delivery through the SQL outbox; it does not own memory
  identity, revision ordering, or projection state
- Remains a compatibility/readability surface during the `legacy` rollout
  **Vector Store Integration:**
- Semantic embedding of tasks and completions
- k-NN search for similar memories
- Metadata filtering on Hebbian scores and timestamps
  **Prometheus Metrics:**
- Agent execution latency, success rates, error counts
- Memory Bus throughput and latency percentiles
- Sandbox violation counts per agent
- Governance approval/rollback metrics

## Consistency Guarantees

- **Canonical atomicity**: a SQL revision, current head, and Obsidian outbox
  event commit together or all roll back.
- **Projection state**: Obsidian delivery is attempted immediately after the
  SQL commit but is not part of that transaction. A failed projection remains
  durable `accepted`, not success, and awaits caller-driven idempotent replay.
- **Idempotency and ordering**: an explicit-key replay returns the original
  revision; a stale replay terminates as `superseded` and cannot overwrite a
  newer current head. Calls without a supplied key are distinct operations.
- **Legacy compatibility**: `legacy` keeps the historical local bus until an
  operator explicitly selects `postgres` or `neon`.

## Performance Targets

| Operation            | p50   | p95   | p99   |
| -------------------- | ----- | ----- | ----- |
| Task routing         | 5ms   | 15ms  | 30ms  |
| Agent lookup         | 2ms   | 8ms   | 20ms  |
| Memory write         | 50ms  | 200ms | 400ms |
| Memory read (exact)  | 10ms  | 50ms  | 100ms |
| Memory read (vector) | 100ms | 300ms | 500ms |
| Hebbian update       | 1ms   | 5ms   | 10ms  |
| Sandbox check        | 2ms   | 10ms  | 20ms  |

## Failure Modes & Recovery

**Provider timeout or rate limit:**

- Classify as `provider_failure` and retain redacted request evidence
- Honor bounded `Retry-After` for Exo 429 responses
- Do not penalize agent trust or Hebbian weight for provider availability
- Preserve a completed response as-is; long output is compressed only after the
  provider call finishes

**Measured agent failure:**

- Classify as `agent_failure`
- Apply the anti-Hebbian update and synchronize execution/trust projections
**Memory Bus Projection Failure:**
- Retain the committed SQL revision and pending outbox event
- Restore projection connectivity, then manually replay the same explicitly
  retained idempotency key to retry deterministic delivery; no worker retries
  pending rows in this slice
- Do not rebuild canonical memory from an Obsidian vault
  **Sandbox Violation:**
- Log violation with context
- Increment violation counter
- Quarantine on 3rd violation
- Prevent further execution pending review
  **Registry Unavailability:**
- Cache recent agent metadata
- Degrade to pre-computed rankings
- Queued requests until recovery

<!--- Eraser file: https://app.eraser.io/workspace/RbH7tUtdYFc15lk1ep9O --->
