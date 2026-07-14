<p><a target="_blank" href="https://app.eraser.io/workspace/olHJAnjmyPJ03fNBzDOT" id="edit-in-eraser-github-link"><img alt="Edit in Eraser" src="https://firebasestorage.googleapis.com/v0/b/second-petal-295822.appspot.com/o/images%2Fgithub%2FOpen%20in%20Eraser.svg?alt=media&amp;token=968381c8-a7e7-472a-8ed6-4a6626da5501"></a></p>

# API Reference
## Overview
Artemis City currently exposes two HTTP surfaces:

1. **FastAPI dashboard API** (`app/api/main.py`): dashboard-oriented `/api/*` endpoints used by the Vite frontend.
2. **TypeScript Express API** (`app/api/index.ts`): external `/api/v1/*` boundary. Supported Python-backed behavior goes through `app/api/lib/pythonBridge.ts`, which calls `python -m src.api_bridge`.

This phase keeps the active `src/` plus `app/api` bridge architecture. It does not introduce `ts_service` or `python_service` directories. Any endpoint shape below that is not listed in the bridge-backed table is planned, not current production behavior.

## Current Express `/api/v1` Surface

All routes below require the Express API authentication middleware except health endpoints.

| Endpoint | Status | Python bridge command |
|---|---|---|
| `GET /api/v1/agents` | Implemented | `registry.list_agents` |
| `GET /api/v1/agents/:id` | Implemented | `registry.get_agent` |
| `GET /api/v1/agents/:id/card` | Implemented | `registry.get_agent` |
| `POST /api/v1/agents` | Implemented | `registry.register_agent` |
| `PUT /api/v1/agents/:id` | Implemented | `registry.update_agent` |
| `DELETE /api/v1/agents/:id` | Implemented | `registry.delete_agent` |
| `POST /api/v1/agents/:id/suspend` | Implemented | `registry.set_agent_status` |
| `POST /api/v1/agents/:id/activate` | Implemented | `registry.set_agent_status` |
| `GET /api/v1/registry/agents` | Implemented | `registry.list_agents` |
| `GET /api/v1/registry/agents/:agentId` | Implemented | `registry.get_agent` |
| `GET /api/v1/registry/agents/:agentId/violations` | Implemented | `registry.get_violations` |
| `POST /api/v1/registry/agents/:agentId/clear-violations` | Implemented | `registry.clear_violations` |
| `PATCH /api/v1/registry/agents/:agentId/trust-tier` | Implemented | `registry.set_trust_tier` |
| `POST /api/v1/governance/agents/:agentId/trust` | Implemented | `governance.compute_trust` |
| `POST /api/v1/governance/updates` | Implemented | `governance.evaluate_update` |
| `GET /api/v1/governance/checkpoints` | Implemented | `governance.checkpoints.list` |
| `GET /api/v1/governance/checkpoints/:checkpointId` | Implemented | `governance.checkpoints.get` |
| `POST /api/v1/governance/checkpoints` | Implemented | `governance.checkpoints.create` |
| `POST /api/v1/governance/checkpoints/:checkpointId/rollback` | Implemented | `governance.checkpoints.rollback` |
| `POST /api/v1/memory/read` | Implemented | `memory.read` |
| `POST /api/v1/memory/write` | Implemented | `memory.write` |
| `POST /api/v1/memory/search` | Implemented | `memory.search` |
| `POST /api/v1/memory/list` | Implemented | `memory.list` |
| `GET /api/v1/memory/stats` | Implemented | `memory.stats` |
| `POST /api/v1/memory/delete` | Implemented | `memory.delete` |
| `POST /api/v1/atp/parse` | Implemented | `atp.parse` |
| `POST /api/v1/atp/validate` | Implemented | `atp.validate` |
| `POST /api/v1/atp/send` | Implemented | `atp.send` |
| `POST /api/v1/atp/route` | Implemented | `atp.route` |
| `GET /api/v1/atp/modes` | Implemented | `atp.modes` |
| `GET /api/v1/atp/priorities` | Implemented | `atp.priorities` |
| `GET /api/v1/atp/action-types` | Implemented | `atp.action_types` |
| `GET /api/v1/atp/template` | Implemented | `atp.template` |
| `POST /api/v1/atp/format` | Implemented | `atp.format` |
| `GET /api/v1/atp/message/:id` | Implemented | `atp.get_message` |
| `GET /api/v1/atp/response/:id` | Implemented | `atp.get_response` |
| `GET /api/v1/atp/queue` | Implemented | `atp.queue` |
| `GET /api/v1/trust/:entityId` | Implemented | `trust.get_score` |
| `POST /api/v1/trust/:entityId/failure` | Implemented | `trust.record_failure` |
| `GET /api/v1/trust/hebbian/weights` | Implemented | `hebbian.weights` |
| `PUT /api/v1/trust/hebbian/weights` | Implemented | `hebbian.update` |
| `GET /api/v1/trust/hebbian/sentinel` | Implemented | `hebbian.sentinel_status` |
| `GET /api/v1/trust/hebbian/sentinel/alerts` | Implemented | `hebbian.sentinel_alerts` |
| `GET /api/v1/trust/levels` | Implemented | `trust.levels` |
| `GET /api/v1/trust/report` | Implemented | `trust.report` |
| `PUT /api/v1/trust/:entityId` | Implemented | `trust.set_score` |
| `POST /api/v1/trust/:entityId/success` | Implemented | `trust.record_success` |
| `GET /api/v1/trust/:entityId/permissions` | Implemented | `trust.permissions` |
| `POST /api/v1/trust/:entityId/can-perform` | Implemented | `trust.can_perform` |

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

| Bridge code | HTTP status |
|---|---:|
| `NOT_FOUND` | 404 |
| `INVALID_REQUEST`, `INVALID_JSON` | 400 |
| `UNKNOWN_COMMAND`, `BRIDGE_ERROR`, `INTERNAL_ERROR`, `BRIDGE_UNAVAILABLE` | 500 |

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
| Tag | Values | Required | Example | Purpose |
| ----- | ----- | ----- | ----- | ----- |
| `#Mode:` | `Build`, `Review`, `Organize`, `Capture`, `Synthesize`, `Commit`, `Reflect` | Recommended | `#Mode: Build` | Overall intent |
| `#Context:` | Free-form text | Recommended | `#Context: Add bridge tests` | Mission goal |
| `#Priority:` | `Critical`, `High`, `Normal`, `Low` | Optional | `#Priority: Normal` | Urgency |
| `#ActionType:` or `#Action:` | `Summarize`, `Scaffold`, `Execute`, `Reflect` | Recommended | `#ActionType: Execute` | Expected response |
| `#TargetZone:` | Path or project area | Optional | `#TargetZone: src/api_bridge.py` | Affected area |
| `#SpecialNotes:` | Free-form text | Optional | `#SpecialNotes: Keep API stable` | Warnings or context |

Canonical parse and validation are implemented in `src/agents/atp/atp_models.py`, `src/agents/atp/atp_parser.py`, and `src/agents/atp/atp_validator.py`, exposed through `atp.parse` and `atp.validate`.

ATP is also a live routing domain. When an execution request contains ATP
headers and does not explicitly pin `required_capability`, Artemis maps the
action and target zone to a capability, strips the headers before dispatch,
and learns against a scope of
`atp:<lowercase-action-type>:<capability>`. An explicit capability always wins.
`atp.route` uses the same registry, trust floor, fallback, and Hebbian blend as
the orchestrator; it no longer performs a metadata-only route.

Every accepted ATP prompt creates a parent provenance event in
`data/run_logs.db`. Routing, dispatch, memory persistence, learning, and task
completion create child events linked by `parent_prov_id`. ATP execution fails
closed if this provenance sink is unavailable. Set `ARTEMIS_ATP_STRICT=1` to
also reject validation errors; the default keeps validation details attached
while preserving compatibility.

## Current FastAPI Dashboard Additions

| Endpoint | Purpose |
|---|---|
| `POST /api/cli/execute` | Executes plain or ATP instructions and returns `atp` plus `provenance_id` with the routing result. |
| `POST /api/cli/execute/stream` | SSE equivalent; routing and complete events include ATP/provenance context. |
| `GET /api/db/hebbian/sentinel` | Current stability state, filterable by `agent_name` and `task_type`. |
| `GET /api/db/hebbian/sentinel/alerts` | Persisted open/resolved alert transitions; `open_only=true` filters active alerts. |

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

- `status`  : Filter by status
- `agent_id`  : Filter by assigned agent
- `created_after`  : ISO 8601 timestamp
- `limit`  : Result limit (default: 100, max: 1000)
- `offset`  : Pagination offset
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
## Planned Memory Bus API
### Write Document
**Endpoint:** `POST /api/v1/memory/write` 

**Request:**

```json
{
  "operation": "write|update|delete",
  "vault": "vault-id",
  "document": {
    "path": "path/to/document.md",
    "content": "# Heading\n\nMarkdown content",
    "frontmatter": {
      "hebbian_weights": {
        "agent_uuid": 0.75
      },
      "tags": ["tag1", "tag2"],
      "created_at": "2026-02-21T10:00:00Z"
    }
  },
  "metadata": {
    "source_agent": "uuid",
    "priority": "high|normal|low",
    "conflict_resolution": "last_write_wins|abort|merge"
  }
}
```
**Response (200 OK):**

```json
{
  "status": "success|conflict",
  "write_id": "uuid",
  "timestamp": "2026-02-21T10:30:00.123Z",
  "latency_ms": 145,
  "content_hash": "sha256_hash",
  "sync_pending": true,
  "estimated_sync_completion": "2026-02-21T10:30:00.300Z"
}
```
### Read Document (Exact)
**Endpoint:** `GET /api/v1/memory/read/exact?path={path}` 

**Response:**

```json
{
  "status": "success|not_found",
  "document": {
    "path": "path/to/document.md",
    "content": "# Heading\n\nMarkdown content",
    "frontmatter": {
      "hebbian_weights": {},
      "created_at": "2026-02-21T10:00:00Z"
    }
  },
  "latency_ms": 45
}
```
### Search Documents (Keyword)
**Endpoint:** `POST /api/v1/memory/search/keyword` 

**Request:**

```json
{
  "terms": ["term1", "term2"],
  "fields": ["title", "tags", "content"],
  "match_mode": "all|any",
  "limit": 20
}
```
**Response:**

```json
{
  "matches": [
    {
      "path": "path/to/document.md",
      "title": "Document Title",
      "excerpt": "...snippet of matching content...",
      "relevance_score": 0.95
    }
  ],
  "total_matches": 1,
  "search_latency_ms": 125
}
```
### Search Documents (Semantic)
**Endpoint:** `POST /api/v1/memory/search/semantic` 

**Request:**

```json
{
  "query": "Find information about data processing",
  "embedding": "optional_precomputed_vector",
  "top_k": 10,
  "filters": {
    "hebbian_weight_min": 0.3,
    "created_after": "2026-01-01T00:00:00Z"
  }
}
```
**Response:**

```json
{
  "matches": [
    {
      "path": "path/to/document.md",
      "content_preview": "First 200 chars of content",
      "similarity_score": 0.92,
      "source_level": "vector_store",
      "hebbian_weights": {
        "agent_uuid": 0.75
      }
    }
  ],
  "total_matches": 15,
  "search_latency_ms": 275
}
```
### Get Memory Health
**Endpoint:** `GET /api/v1/memory/health` 

**Response:**

```json
{
  "status": "healthy|degraded|unhealthy",
  "components": {
    "obsidian": {
      "status": "up",
      "latency_ms": 5,
      "sync_lag_ms": 0
    },
    "vector_store": {
      "status": "up",
      "latency_ms": 150,
      "sync_lag_ms": 45
    }
  },
  "stats": {
    "total_documents": 10523,
    "total_size_mb": 256,
    "cache_hit_ratio": 0.75,
    "last_sync": "2026-02-21T10:30:15Z"
  }
}
```
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

- `capability`  : Filter by capability
- `status`  : Filter by status
- `trust_tier`  : Filter by tier
- `limit`  : Result limit
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
| Code | HTTP | Meaning |
| ----- | ----- | ----- |
| `INVALID_REQUEST`  | 400 | Malformed request |
| `UNAUTHORIZED`  | 401 | Missing/invalid authentication |
| `FORBIDDEN`  | 403 | Insufficient permissions |
| `NOT_FOUND`  | 404 | Resource not found |
| `CONFLICT`  | 409 | Write conflict |
| `RATE_LIMITED`  | 429 | Rate limit exceeded |
| `SERVICE_UNAVAILABLE`  | 503 | Service temporarily down |
| `TIMEOUT`  | 504 | Request timeout |
## Rate Limiting
All endpoints subject to rate limiting:

- Default: 100 requests/minute per API key
- Burst: 200 requests for 10 seconds
- Headers:
    - `X-RateLimit-Limit`  : Requests per minute
    - `X-RateLimit-Remaining`  : Remaining requests
    - `X-RateLimit-Reset`  : Unix timestamp of reset

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
