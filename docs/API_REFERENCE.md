<p><a target="_blank" href="https://app.eraser.io/workspace/olHJAnjmyPJ03fNBzDOT" id="edit-in-eraser-github-link"><img alt="Edit in Eraser" src="https://firebasestorage.googleapis.com/v0/b/second-petal-295822.appspot.com/o/images%2Fgithub%2FOpen%20in%20Eraser.svg?alt=media&amp;token=968381c8-a7e7-472a-8ed6-4a6626da5501"></a></p>

# API Reference

## Overview

Artemis City currently exposes two HTTP surfaces:

1. **FastAPI dashboard API** (`app/api/main.py`): dashboard-oriented `/api/*` endpoints used by the Vite frontend.
2. **TypeScript Express API** (`app/api/index.ts`): external `/api/v1/*` boundary. Supported Python-backed behavior goes through `app/api/lib/pythonBridge.ts`, which calls `python -m src.api_bridge`.

This phase keeps the active `src/` plus `app/api` bridge architecture. It does not introduce `ts_service` or `python_service` directories. Any endpoint shape below that is not listed in the bridge-backed table is planned, not current production behavior.

### Transport-neutral Python contracts

Two current Python libraries sit below the transports:

- `src.validation.ATPValidationService` exposes typed `parse`, `validate`, and
  `format` operations over the canonical ATP parser/validator. It returns
  immutable Pydantic contracts and stable issue codes. `services/mcp/artemis-validation/`
  registers it as a read-only, authenticated, stdio-only MCP transport over the
  official SDK; current Express ATP routes continue through their listed
  bridge commands unchanged.
- `src.auth` defines credential-free authentication receipts, authority
  contexts, delegation references, and the Authstructure verifier port. The
  production configuration loader intentionally fails closed until the external
  Authstructure verifier contract is enabled and conformant.

Rendered signatures and docstrings are in
[`PYTHON_API.md`](PYTHON_API.md).

## Current Express `/api/v1` Surface

All routes below require the Express API authentication middleware except health endpoints.

| Endpoint                                                               | Status                                   | Python bridge command             |
| ---------------------------------------------------------------------- | ---------------------------------------- | --------------------------------- |
| `GET /api/v1/agents`                                                   | Implemented                              | `registry.list_agents`            |
| `GET /api/v1/agents/:id`                                               | Implemented                              | `registry.get_agent`              |
| `GET /api/v1/agents/:id/card`                                          | Implemented                              | `registry.get_agent`              |
| `POST /api/v1/agents`                                                  | Implemented                              | `registry.register_agent`         |
| `PUT /api/v1/agents/:id`                                               | Implemented                              | `registry.update_agent`           |
| `DELETE /api/v1/agents/:id`                                            | Implemented                              | `registry.delete_agent`           |
| `POST /api/v1/agents/:id/suspend`                                      | Implemented                              | `registry.set_agent_status`       |
| `POST /api/v1/agents/:id/activate`                                     | Implemented                              | `registry.set_agent_status`       |
| `GET /api/v1/registry/agents`                                          | Implemented                              | `registry.list_agents`            |
| `GET /api/v1/registry/agents/:agentId`                                 | Implemented                              | `registry.get_agent`              |
| `GET /api/v1/registry/agents/:agentId/violations`                      | Implemented                              | `registry.get_violations`         |
| `POST /api/v1/registry/agents/:agentId/clear-violations`               | Implemented                              | `registry.clear_violations`       |
| `PATCH /api/v1/registry/agents/:agentId/trust-tier`                    | Implemented                              | `registry.set_trust_tier`         |
| `POST /api/v1/governance/agents/:agentId/trust`                        | Implemented                              | `governance.compute_trust`        |
| `POST /api/v1/governance/updates`                                      | Implemented                              | `governance.evaluate_update`      |
| `GET /api/v1/governance/checkpoints`                                   | Implemented                              | `governance.checkpoints.list`     |
| `GET /api/v1/governance/checkpoints/:checkpointId`                     | Implemented                              | `governance.checkpoints.get`      |
| `POST /api/v1/governance/checkpoints`                                  | Implemented                              | `governance.checkpoints.create`   |
| `POST /api/v1/governance/checkpoints/:checkpointId/rollback`           | Implemented                              | `governance.checkpoints.rollback` |
| `POST /api/v1/memory/read`                                             | Implemented                              | `memory.read`                     |
| `POST /api/v1/memory/write`                                            | Implemented                              | `memory.write`                    |
| `POST /api/v1/memory/search`                                           | Implemented                              | `memory.search`                   |
| `POST /api/v1/memory/list`                                             | Implemented                              | `memory.list`                     |
| `GET /api/v1/memory/stats`                                             | Implemented                              | `memory.stats`                    |
| `POST /api/v1/memory/delete`                                           | Implemented                              | `memory.delete`                   |
| `POST /api/v1/atp/parse`                                               | Implemented                              | `atp.parse`                       |
| `POST /api/v1/atp/validate`                                            | Implemented                              | `atp.validate`                    |
| `POST /api/v1/atp/send`                                                | Implemented                              | `atp.send`                        |
| `POST /api/v1/atp/route`                                               | Implemented                              | `atp.route`                       |
| `GET /api/v1/atp/modes`                                                | Implemented                              | `atp.modes`                       |
| `GET /api/v1/atp/priorities`                                           | Implemented                              | `atp.priorities`                  |
| `GET /api/v1/atp/action-types`                                         | Implemented                              | `atp.action_types`                |
| `GET /api/v1/atp/template`                                             | Implemented                              | `atp.template`                    |
| `POST /api/v1/atp/format`                                              | Implemented                              | `atp.format`                      |
| `GET /api/v1/atp/message/:id`                                          | Implemented                              | `atp.get_message`                 |
| `GET /api/v1/atp/response/:id`                                         | Implemented                              | `atp.get_response`                |
| `GET /api/v1/atp/queue`                                                | Implemented                              | `atp.queue`                       |
| `GET /api/v1/trust/:entityId`                                          | Implemented                              | `trust.get_score`                 |
| `POST /api/v1/trust/:entityId/failure`                                 | Implemented                              | `trust.record_failure`            |
| `GET /api/v1/trust/hebbian/weights`                                    | Implemented                              | `hebbian.weights`                 |
| `PUT /api/v1/trust/hebbian/weights`                                    | Implemented                              | `hebbian.update`                  |
| `GET /api/v1/trust/hebbian/sentinel`                                   | Implemented                              | `hebbian.sentinel_status`         |
| `GET /api/v1/trust/hebbian/sentinel/alerts`                            | Implemented                              | `hebbian.sentinel_alerts`         |
| `GET /api/v1/trust/levels`                                             | Implemented                              | `trust.levels`                    |
| `GET /api/v1/trust/report`                                             | Implemented                              | `trust.report`                    |
| `PUT /api/v1/trust/:entityId`                                          | Implemented                              | `trust.set_score`                 |
| `POST /api/v1/trust/:entityId/success`                                 | Implemented                              | `trust.record_success`            |
| `GET /api/v1/trust/:entityId/permissions`                              | Implemented                              | `trust.permissions`               |
| `POST /api/v1/trust/:entityId/can-perform`                             | Implemented                              | `trust.can_perform`               |
| `POST /api/v1/llm/chat`                                                | Implemented                              | `llm.chat`                        |
| `POST /api/v1/llm/complete`                                            | Implemented                              | `llm.complete`                    |
| `GET /api/v1/llm/models`                                               | Implemented (configured state)           | `llm.config`                      |
| `GET /api/v1/llm/providers`                                            | Implemented (redacted environment state) | `llm.config`                      |
| `POST /api/v1/llm/embed`, `/stream`, `/provider`, `/atp`; `GET /usage` | Explicit `501`                           | None; no simulated fallback       |

Trust mutations are write-through for agent entities: the bridge synchronizes
the authoritative registry projection and `data/trust_scores.db`. Governance
violations recalculate trust from execution history plus active violations but
do not themselves alter capability-scoped Hebbian weights. A completed task
updates both systems from the same outcome: it applies the Hebbian/anti-Hebbian
rule, mirrors learning into `data/agent_registry.db`, recomputes governance
trust, and synchronizes `data/trust_scores.db`. Manual Hebbian edits refresh the
corresponding registry learning summary without incrementing execution counts.

The Sentinel endpoints expose the rolling sign-change rate of recent outcomes
for each `(agent_name, task_type)` association and its persisted alert
transitions. Sentinel is observational: it does not change weights, trust,
quarantine state, or routing rank. Operators or governance policy can use the
alerts as review evidence without creating a hidden feedback loop.

Checkpoint rollback requires both `confirmed: true` and `initiated_by`. The
checkpoint integrity hash is verified before atomically restoring registry and
Hebbian snapshots; restored registry trust is then reconciled into the trust
projection.

### Bridge Error Mapping

| Bridge code                                                               | HTTP status |
| ------------------------------------------------------------------------- | ----------: |
| `NOT_FOUND`                                                               |         404 |
| `INVALID_REQUEST`, `INVALID_JSON`                                         |         400 |
| `FORBIDDEN`                                                               |         403 |
| `RATE_LIMITED`                                                            |         429 |
| `PROVIDER_ERROR`                                                          |         502 |
| `SERVICE_UNAVAILABLE`                                                     |         503 |
| `TIMEOUT`                                                                 |         504 |
| `UNKNOWN_COMMAND`, `BRIDGE_ERROR`, `INTERNAL_ERROR`, `BRIDGE_UNAVAILABLE` |         500 |

## Agent Transmission Protocol (ATP)

ATP is the structured message format for agent-to-agent communication and kernel-to-agent direction.

### ATP Message Format

```
#Mode: Build
#Context: Brief mission goal
#Priority: Normal
#ActionType: Execute
#TargetZone: src/
#SpecialNotes: Optional notes

<message_body>
```

### ATP Tags Specification

| Tag                          | Values                                                                      | Required    | Example                          | Purpose             |
| ---------------------------- | --------------------------------------------------------------------------- | ----------- | -------------------------------- | ------------------- |
| `#Mode:`                     | `Build`, `Review`, `Organize`, `Capture`, `Synthesize`, `Commit`, `Reflect` | Recommended | `#Mode: Build`                   | Overall intent      |
| `#Context:`                  | Free-form text                                                              | Recommended | `#Context: Add bridge tests`     | Mission goal        |
| `#Priority:`                 | `Critical`, `High`, `Normal`, `Low`                                         | Optional    | `#Priority: Normal`              | Urgency             |
| `#ActionType:` or `#Action:` | `Summarize`, `Scaffold`, `Execute`, `Reflect`                               | Recommended | `#ActionType: Execute`           | Expected response   |
| `#TargetZone:`               | Path or project area                                                        | Optional    | `#TargetZone: src/api_bridge.py` | Affected area       |
| `#SpecialNotes:`             | Free-form text                                                              | Optional    | `#SpecialNotes: Keep API stable` | Warnings or context |

Canonical parsing and validation are implemented in
`src/agents/atp/atp_models.py`, `src/agents/atp/atp_parser.py`, and
`src/agents/atp/atp_validator.py`. `src.validation.ATPValidationService` is the
typed transport-neutral facade over those implementations. Existing Express
routes expose the bridge commands `atp.parse` and `atp.validate`.

ATP is also a live routing domain. When an execution request contains ATP
headers and does not explicitly pin `required_capability`, Artemis maps the
action and target zone to a capability, strips the headers before dispatch,
and learns against a scope of
`atp:<lowercase-action-type>:<capability>`. An explicit capability may narrow
the ATP-authorized domain but cannot widen it.
`atp.route` uses the same registry, trust floor, fallback, and Hebbian blend as
the orchestrator; it no longer performs a metadata-only route.

Every accepted ATP prompt creates a parent provenance event in
`data/run_logs.db`. Routing, dispatch, memory persistence, learning, and task
completion create child events linked by `parent_prov_id`. ATP execution fails
closed if this provenance sink is unavailable. Set `ARTEMIS_ATP_STRICT=1` to
also reject validation errors; the default keeps validation details attached
while preserving compatibility.

## Current FastAPI Dashboard Additions

| Endpoint                              | Purpose                                                                                                                                                                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/cli/execute`               | Executes plain or ATP instructions and returns routing/provenance plus verified `provider`, `fallback_used`, `model`, `outcome_class`, `learning_eligible`, `exo_request`, and optional `output_compression` evidence. Also returns `routing_path`.           |
| `POST /api/cli/execute/stream`        | SSE equivalent; emits heartbeats during long inference and returns the same provider/compression evidence in `complete`. The `routing` and `complete` frames both carry `routing_path`.                                                                       |
| `GET /api/db/hebbian/sentinel`        | Current stability state, filterable by `agent_name` and `task_type`.                                                                                                                                                                                          |
| `GET /api/db/hebbian/sentinel/alerts` | Persisted open/resolved alert transitions; `open_only=true` filters active alerts.                                                                                                                                                                            |
| `GET /api/routing/config`             | Live routing configuration used to label decisions in the UI: kernel/Hebbian toggles, blend weights, trust floor, fallback capability, Sentinel settings, the reviewed-domain capability list, and the advertised capabilities labelled by `kernel_reviewed`. |
| `GET /api/db/trust`                   | Persisted trust scores from `data/trust_scores.db`; `entity_type` filters the entity family. Read-only.                                                                                                                                                       |
| `GET /api/db/violations`              | Sandbox and governance violations; `agent_name` and `open_only` filter. Read-only — clearing a violation stays a governance action.                                                                                                                           |
| `GET /api/db/delegation/grants`       | Delegation-grant ledger metadata. The signed `payload` and its `grant_hash` are deliberately never served.                                                                                                                                                    |
| `GET /api/db/delegation/reservations` | Budget reservations backing delegated routing.                                                                                                                                                                                                                |

### Routing path labelling

Every routed execution reports which routing implementation served it, so an
authorized kernel route stays distinguishable from a compatibility route
without reading server logs. The vocabulary is `ROUTING_PATHS` in
`src/integration/hebbian_router.py`:

| `routing_path`                 | Meaning                                                                                                                                                   |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kernel`                       | Served by the shared Routing Kernel: intent → authorization → eligibility → Hebbian ranking. Stamped by the kernel itself, so it holds for every ingress. |
| `hebbian_router`               | Produced by the legacy router with no kernel involved.                                                                                                    |
| `legacy_unreviewed_capability` | The capability has no reviewed ATP execution domain, so the kernel declined and the legacy path served the task without kernel authorization.             |
| `legacy_kernel_unavailable`    | The kernel was disabled or failed to build at boot.                                                                                                       |
| `pinned`                       | No routing ran: the caller named the agent. Ingress-level label; the response carries no decision object.                                                 |
| `registry_composite`           | Hebbian routing is disabled; the registry ranked on composite score alone. Ingress-level label.                                                           |

`RoutingDecision.to_dict()` carries the field for routed calls, and
`ExecuteInstructionResponse.routing_path` mirrors it so pinned and
composite-only calls are labelled too.

### Exo execution evidence and long output

A successful Exo result is identifiable by `provider: "exo"` and an
`exo_request` object containing the concrete request endpoint, HTTP status,
latency, stable client request ID, server/response IDs when supplied, requested
and observed models, attempt history, content length, and content SHA-256. The
object never contains the API key or prompt. Provider failures are explicit;
they remain `status: "failed"`, carry `fallback_used: false`, and cannot be
converted to an unlabelled successful fallback. Streaming failures do not emit
locally generated fallback tokens.

The client uses separate connect/read timeouts (10 and 900 seconds by default)
and honors bounded `Retry-After` for HTTP 429 plus transient 502/503/504 and
connect failures. Read timeouts and partially emitted streams are not replayed.
Set `EXO_READ_TIMEOUT_SECONDS=0` only when an unlimited provider wait is
intentional.

When complete normalized Exo text exceeds `ARTEMIS_EXO_SUMMARY_THRESHOLD_CHARS` (12000 by
default), it is stored as a non-embedded raw artifact and SHA-256 linked from
`output_compression`. A governed child task routes over agents advertising
`text_summarization`; its dedicated Hebbian scope records which summarizer best
compresses context for follow-on agents. `compressed_context` and the terminal
`summary` carry the condensed result. Live SSE may display the original token
deltas before that terminal compression step.

### ATP Message Examples

#### Example 1: Query Task from Memory Bus

```
#Mode: Synthesize
#Context: Find tasks related to data processing
#Priority: High
#ActionType: Summarize
#TargetZone: memory
#SpecialNotes: require_semantic_match=true

{
  "query_type": "semantic",
  "text": "Find tasks related to data processing",
  "top_k": 5,
  "filters": {
    "hebbian_weight_min": 0.6,
    "created_after": "2026-02-15T00:00:00Z"
  }
}
```

#### Example 2: Submit Task for Execution (Kernel)

```
#Mode: Build
#Context: Submit a task for execution
#Priority: Normal
#ActionType: Execute
#TargetZone: kernel

{
  "task": {
    "id": "task-uuid",
    "type": "text-analysis",
    "input": "Analyze the following document...",
    "required_capabilities": ["nlp", "sentiment-analysis"],
    "timeout_seconds": 300,
    "agent_preference": null
  }
}
```

#### Example 3: Batch Agent Communication

```
#Mode: Organize
#Context: Batch registry synchronization
#Priority: Normal
#ActionType: Execute
#TargetZone: registry

{
  "operations": [
    {
      "agent_id": "agent-uuid-1",
      "field": "accuracy_score",
      "value": 0.92
    },
    {
      "agent_id": "agent-uuid-2",
      "field": "efficiency_score",
      "value": 0.87
    }
  ]
}
```

#### Example 4: Async Governance Update Proposal

```
#Mode: Review
#Context: Evaluate an update proposal
#Priority: High
#ActionType: Reflect
#TargetZone: governance
#SpecialNotes: trust_score=0.85, risk_tier=monitored

{
  "update_id": "uuid",
  "agent_id": "uuid",
  "update_type": "patch",
  "description": "Fix memory leak in task router",
  "changes": {
    "files_modified": ["src/kernel.py"],
    "lines_added": 15,
    "lines_deleted": 8
  },
  "checkpoint_id": "uuid"
}
```

## Planned Kernel API

### Submit Task

**Endpoint:** `POST /api/v1/tasks`

**Request:**

```json
{
  "id": "task-uuid (optional, generated if omitted)",
  "type": "string (required, task type identifier)",
  "input": "any (required, task input)",
  "required_capabilities": ["string"],
  "timeout_seconds": 300,
  "agent_preference": "uuid (optional, preferred agent)",
  "metadata": {
    "user_id": "uuid",
    "priority": "high|normal|low",
    "retry_count": 0,
    "tags": ["tag1", "tag2"]
  }
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "uuid",
  "status": "queued|executing|pending_approval",
  "estimated_start": "2026-02-21T10:30:00Z",
  "estimated_completion": "2026-02-21T10:35:00Z"
}
```

### Get Task Status

**Endpoint:** `GET /api/v1/tasks/{task_id}`

**Response:**

```json
{
  "task_id": "uuid",
  "status": "queued|executing|completed|failed|aborted",
  "assigned_agent": "uuid",
  "start_time": "2026-02-21T10:30:00Z",
  "completion_time": "2026-02-21T10:32:45Z",
  "duration_ms": 165000,
  "result": "any",
  "error": null
}
```

### Cancel Task

**Endpoint:** `POST /api/v1/tasks/{task_id}/cancel`

**Response:**

```json
{
  "task_id": "uuid",
  "status": "cancelled",
  "cancelled_at": "2026-02-21T10:31:00Z"
}
```

### List Tasks

**Endpoint:** `GET /api/v1/tasks?status=completed&limit=100&offset=0`

**Query Parameters:**

- `status` : Filter by status
- `agent_id` : Filter by assigned agent
- `created_after` : ISO 8601 timestamp
- `limit` : Result limit (default: 100, max: 1000)
- `offset` : Pagination offset
  **Response:**

```json
{
  "tasks": [
    {
      "task_id": "uuid",
      "status": "completed",
      "assigned_agent": "uuid",
      "type": "string",
      "created_at": "2026-02-21T10:00:00Z",
      "completed_at": "2026-02-21T10:02:45Z"
    }
  ],
  "total": 5000,
  "limit": 100,
  "offset": 0
}
```

## Memory Bus API

These mounted Express routes delegate to the Python Memory Bus. In explicit
PostgreSQL/Neon mode, SQL is canonical and Obsidian/vector state is a derived
projection.

### Write Document

**Endpoint:** `POST /api/v1/memory/write`

```json
{
  "path": "Notes/example.md",
  "content": "# Canonical memory",
  "metadata": { "kind": "brief" },
  "embed": true,
  "idempotency_key": "optional-operation-key",
  "provenance_id": "optional-uuid",
  "source_agent": "optional-agent-name"
}
```

`path` and `content` are required. All other fields are optional. Reuse the
same `idempotency_key` only to replay the same path/content operation.

Synchronized writes return HTTP 200. A durable SQL commit whose projection is
pending returns HTTP 202; this is accepted, not failed:

```json
{
  "success": true,
  "message": "Memory write accepted; projection pending",
  "data": {
    "status": "accepted",
    "record_id": "uuid",
    "event_id": "uuid",
    "revision": 1,
    "idempotency_key": "operation-key",
    "sql_status": "committed",
    "obsidian_status": "pending",
    "vector_status": "pending",
    "sync_pending": true,
    "duplicate": false
  }
}
```

Retain `idempotency_key` to replay a pending projection. The initial slice has
no background outbox worker.

### Read, Search, List, and Stats

- `POST /api/v1/memory/read` with `{"path":"Notes/example.md"}` performs an
  exact read. SQL mode never substitutes stale Obsidian bytes for a missing
  SQL head.
- `POST /api/v1/memory/search` accepts `query`, optional `path`, `tags`, and
  `limit`. SQL mode uses an optional exact SQL path and the derived vector
  index; Obsidian keyword scan is legacy-only.
- `POST /api/v1/memory/list` accepts optional `path`. SQL responses are labeled
  `source=sql`.
- `GET /api/v1/memory/stats` reports canonical SQL note/byte counts in SQL
  mode. `vector_count` is `null` and `projection_stats` is `not_checked`.

`POST /api/v1/memory/delete` retains legacy behavior. SQL mode returns
`MEMORY_DELETE_UNSUPPORTED` (HTTP 409) until canonical tombstones exist.

## Planned Agent Registry API

### Register Agent

**Endpoint:** `POST /api/v1/registry/agents`

**Request:**

```json
{
  "name": "string (required, agent name)",
  "capabilities": ["string"],
  "alignment_score": 0.85,
  "accuracy_score": 0.92,
  "efficiency_score": 0.88,
  "trust_tier": "auto|monitored|human",
  "sandbox_whitelist": {
    "tools": [
      {
        "name": "file_read",
        "paths": ["/data/public/**"],
        "operations": ["read"],
        "rate_limit": 100
      }
    ],
    "network": {
      "allowlist": ["api.example.com"],
      "ports": [80, 443]
    }
  }
}
```

**Response (201 Created):**

```json
{
  "agent_id": "uuid",
  "name": "string",
  "status": "active",
  "created_at": "2026-02-21T10:30:00Z"
}
```

### Get Agent

**Endpoint:** `GET /api/v1/registry/agents/{agent_id}`

**Response:**

```json
{
  "agent_id": "uuid",
  "name": "string",
  "capabilities": ["string"],
  "alignment_score": 0.85,
  "accuracy_score": 0.92,
  "efficiency_score": 0.88,
  "trust_tier": "auto|monitored|human",
  "trust_score": 0.89,
  "status": "active|suspended|quarantined",
  "violation_count": 0,
  "last_task": "2026-02-21T10:25:00Z",
  "updated_at": "2026-02-21T10:30:00Z"
}
```

### List Agents

**Endpoint:** `GET /api/v1/registry/agents?capability=nlp&status=active&limit=100`

**Query Parameters:**

- `capability` : Filter by capability
- `status` : Filter by status
- `trust_tier` : Filter by tier
- `limit` : Result limit
  **Response:**

```json
{
  "agents": [
    {
      "agent_id": "uuid",
      "name": "string",
      "capabilities": ["string"],
      "trust_score": 0.89,
      "status": "active"
    }
  ],
  "total": 45,
  "limit": 100,
  "offset": 0
}
```

### Update Agent Scores

**Endpoint:** `PATCH /api/v1/registry/agents/{agent_id}`

**Request:**

```json
{
  "alignment_score": 0.85,
  "accuracy_score": 0.92,
  "efficiency_score": 0.88
}
```

**Response:**

```json
{
  "agent_id": "uuid",
  "alignment_score": 0.85,
  "accuracy_score": 0.92,
  "efficiency_score": 0.88,
  "updated_at": "2026-02-21T10:30:00Z"
}
```

### Get Agent Violations

**Endpoint:** `GET /api/v1/registry/agents/{agent_id}/violations`

**Response:**

```json
{
  "agent_id": "uuid",
  "violation_count": 3,
  "quarantined": true,
  "violations": [
    {
      "violation_id": "uuid",
      "timestamp": "2026-02-21T10:15:00Z",
      "type": "unauthorized_tool",
      "details": "Attempted access to /etc/passwd"
    }
  ]
}
```

### Clear Agent Violations

**Endpoint:** `POST /api/v1/registry/agents/{agent_id}/clear-violations`

**Request:**

```json
{
  "override_tier": "monitored",
  "rationale": "Manual review confirms safe behavior"
}
```

**Response:**

```json
{
  "agent_id": "uuid",
  "violation_count": 0,
  "quarantined": false,
  "overridden_by": "admin_uuid",
  "override_timestamp": "2026-02-21T10:30:00Z"
}
```

## Planned Governance API

### Propose Update

**Endpoint:** `POST /api/v1/governance/updates`

**Request:** (See ATP Example 4 in section above)

**Response (202 Accepted):**

```json
{
  "update_id": "uuid",
  "status": "submitted|approved|rejected",
  "tier": 1,
  "approval_deadline": "2026-02-21T10:35:00Z"
}
```

### Get Update Status

**Endpoint:** `GET /api/v1/governance/updates/{update_id}`

**Response:**

```json
{
  "update_id": "uuid",
  "agent_id": "uuid",
  "status": "submitted|approved|rejected|deploying|deployed|rolled_back",
  "tier": 2,
  "submitted_at": "2026-02-21T10:30:00Z",
  "approved_at": "2026-02-21T11:00:00Z",
  "deployed_at": "2026-02-21T11:05:00Z",
  "test_results": {
    "unit_tests": { "passed": 1247, "failed": 0 },
    "integration_tests": { "passed": 156, "failed": 0 }
  }
}
```

### List Pending Approvals

**Endpoint:** `GET /api/v1/governance/approvals?tier=2&status=pending`

**Response:**

```json
{
  "pending": [
    {
      "update_id": "uuid",
      "agent_id": "uuid",
      "tier": 2,
      "submitted_at": "2026-02-21T10:30:00Z",
      "deadline": "2026-02-21T11:30:00Z"
    }
  ],
  "count": 2,
  "overdue": 0
}
```

### Approve Update

**Endpoint:** `POST /api/v1/governance/updates/{update_id}/approve`

**Request:**

```json
{
  "approved_by": "admin_uuid",
  "rationale": "Code review passed, all tests green",
  "override_risk": false
}
```

**Response:**

```json
{
  "update_id": "uuid",
  "status": "approved",
  "deployment_scheduled": true,
  "deployment_time": "2026-02-21T11:05:00Z"
}
```

### Reject Update

**Endpoint:** `POST /api/v1/governance/updates/{update_id}/reject`

**Request:**

```json
{
  "rejected_by": "admin_uuid",
  "reason": "Breaking API change not justified",
  "feedback": "Please refactor to maintain backwards compatibility"
}
```

**Response:**

```json
{
  "update_id": "uuid",
  "status": "rejected",
  "rejected_at": "2026-02-21T10:35:00Z"
}
```

### Propose Rollback

**Endpoint:** `POST /api/v1/governance/rollbacks`

**Request:**

```json
{
  "checkpoint_id": "uuid",
  "initiated_by": "admin_uuid",
  "reason": "error_detected",
  "details": "Anomaly: error rate > 5%"
}
```

**Response (202 Accepted):**

```json
{
  "rollback_id": "uuid",
  "checkpoint_id": "uuid",
  "status": "initiated|in_progress|completed|failed",
  "estimated_completion": "2026-02-21T10:45:00Z"
}
```

### Get Rollback Status

**Endpoint:** `GET /api/v1/governance/rollbacks/{rollback_id}`

**Response:**

```json
{
  "rollback_id": "uuid",
  "checkpoint_id": "uuid",
  "status": "completed",
  "initiated_at": "2026-02-21T10:35:00Z",
  "completed_at": "2026-02-21T10:42:00Z",
  "verified": true,
  "notes": "System restored to stable state"
}
```

## Planned Hebbian Learning API

### Get Hebbian Weights

**Endpoint:** `GET /api/v1/hebbian/weights?agent_id={agent_id}`

**Response:**

```json
{
  "agent_id": "uuid",
  "weights": {
    "task_type_1": 0.75,
    "task_type_2": 0.45,
    "task_type_3": 0.92
  },
  "last_updated": "2026-02-21T10:30:00Z"
}
```

### Get Learning History

**Endpoint:** `GET /api/v1/hebbian/history/{agent_id}?limit=100`

**Response:**

```json
{
  "agent_id": "uuid",
  "history": [
    {
      "timestamp": "2026-02-21T10:25:00Z",
      "task_type": "text-analysis",
      "delta": 1,
      "result": "success",
      "weight_before": 0.74,
      "weight_after": 0.75
    }
  ],
  "total_entries": 542,
  "limit": 100
}
```

## Error Responses

All error responses follow this format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {
      "field": "optional field-specific errors"
    },
    "request_id": "uuid (for tracing)"
  }
}
```

### Common Error Codes

| Code                  | HTTP | Meaning                        |
| --------------------- | ---- | ------------------------------ |
| `INVALID_REQUEST`     | 400  | Malformed request              |
| `UNAUTHORIZED`        | 401  | Missing/invalid authentication |
| `FORBIDDEN`           | 403  | Insufficient permissions       |
| `NOT_FOUND`           | 404  | Resource not found             |
| `CONFLICT`            | 409  | Write conflict                 |
| `RATE_LIMITED`        | 429  | Rate limit exceeded            |
| `SERVICE_UNAVAILABLE` | 503  | Service temporarily down       |
| `TIMEOUT`             | 504  | Request timeout                |

## Rate Limiting

Protected Express `/api/v1/*` endpoints are limited per authenticated API key.
The defaults are 100 request starts per 60-second window and can be changed
with `ARTEMIS_API_RATE_LIMIT_MAX_REQUESTS` and
`ARTEMIS_API_RATE_LIMIT_WINDOW_MS`. A long-running Exo request consumes one
slot when it begins; elapsed generation time does not consume more quota.

- Headers:
  - `X-RateLimit-Limit` : Requests per minute
  - `X-RateLimit-Remaining` : Remaining requests
  - `X-RateLimit-Reset` : Unix timestamp of reset
  - `Retry-After` : Seconds until retry (429 responses)

Exo's own independent 429 limit is handled by the Python client using bounded
`Retry-After` retries. An upstream 429 is a provider-availability outcome, not
an agent governance violation, and therefore does not change agent trust or
Hebbian weight. If retries are exhausted, the Express LLM route forwards safe
numeric retry guidance in its own `Retry-After` response header.

## Authentication

Use Bearer token in Authorization header:

```
Authorization: Bearer <api_key>
```

API keys provisioned per agent/user. Scopes restrict which endpoints are accessible.

## Planned Webhook Events

Subscribe to events via `POST /api/v1/webhooks`:

```json
{
  "url": "https://example.com/webhook",
  "events": ["task.completed", "update.approved", "agent.quarantined"]
}
```

Event payload:

```json
{
  "event": "task.completed",
  "timestamp": "2026-02-21T10:30:00Z",
  "data": {
    "task_id": "uuid",
    "status": "completed",
    "result": "any"
  }
}
```

<!--- Eraser file: https://app.eraser.io/workspace/olHJAnjmyPJ03fNBzDOT --->
