# API Reference

## Overview

Artemis City exposes three primary API surfaces:
1. **Agent API**: Task submission and execution
2. **ATP (Artemis Transmission Protocol)**: Structured inter-agent messaging
3. **System APIs**: Registry, Memory Bus, Governance (admin-only)

All APIs use HTTP/JSON for REST endpoints and support gRPC where noted.

## Agent Transmission Protocol (ATP)

ATP is the structured message format for agent-to-agent communication and kernel-to-agent direction.

### ATP Message Format

```
#Mode <mode>
#Context <context_id>
#Priority <priority_level>
#ActionType <action_type>
#TargetZone <zone_identifier>
#SpecialNotes <notes>

<message_body>
```

### ATP Tags Specification

| Tag | Values | Required | Example | Purpose |
|-----|--------|----------|---------|---------|
| `#Mode` | `direct`, `batch`, `stream`, `async` | Yes | `#Mode direct` | Communication mode |
| `#Context` | UUID, string (max 64 chars) | Yes | `#Context exec-2026-02-21-xyz` | Trace/correlation ID |
| `#Priority` | `critical` (0), `high` (1), `normal` (2), `low` (3) | Yes | `#Priority high` | Queue priority |
| `#ActionType` | See section below | Yes | `#ActionType query` | What agent should do |
| `#TargetZone` | `kernel`, `registry`, `memory`, `sandbox`, `governance` | Yes | `#TargetZone memory` | System component target |
| `#SpecialNotes` | String (max 256 chars) | No | `#SpecialNotes retry on timeout` | Metadata/hints |

### ActionType Values

**Query Operations:**
- `query`: Read/lookup operation
- `search`: Semantic or keyword search
- `list`: Enumerate items
- `get_status`: Check current state

**Modification Operations:**
- `create`: Insert new record
- `update`: Modify existing record
- `delete`: Remove record
- `upsert`: Create or update

**Execution Operations:**
- `execute`: Run task/agent
- `schedule`: Queue for later execution
- `cancel`: Abort running task
- `retry`: Re-execute failed task

**Management Operations:**
- `register`: Register agent or capability
- `revoke`: Remove registration
- `approve`: Approve pending action
- `reject`: Deny pending action

**Governance Operations:**
- `propose_update`: Submit self-update
- `rollback`: Revert to checkpoint
- `override`: Bypass policy check

### ATP Message Examples

#### Example 1: Query Task from Memory Bus

```
#Mode direct
#Context task-exec-2026-02-21-abc123
#Priority high
#ActionType query
#TargetZone memory
#SpecialNotes require_semantic_match=true

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
#Mode direct
#Context user-request-2026-02-21-xyz789
#Priority normal
#ActionType execute
#TargetZone kernel

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
#Mode batch
#Context batch-sync-2026-02-21-batch001
#Priority normal
#ActionType update
#TargetZone registry

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
#Mode async
#Context update-proposal-2026-02-21-tier2
#Priority high
#ActionType propose_update
#TargetZone governance
#SpecialNotes trust_score=0.85, risk_tier=monitored

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

## Kernel API

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
- `status`: Filter by status
- `agent_id`: Filter by assigned agent
- `created_after`: ISO 8601 timestamp
- `limit`: Result limit (default: 100, max: 1000)
- `offset`: Pagination offset

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

## Agent Registry API

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
- `capability`: Filter by capability
- `status`: Filter by status
- `trust_tier`: Filter by tier
- `limit`: Result limit

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

## Governance API

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

## Hebbian Learning API

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
|------|------|---------|
| `INVALID_REQUEST` | 400 | Malformed request |
| `UNAUTHORIZED` | 401 | Missing/invalid authentication |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `CONFLICT` | 409 | Write conflict |
| `RATE_LIMITED` | 429 | Rate limit exceeded |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily down |
| `TIMEOUT` | 504 | Request timeout |

## Rate Limiting

All endpoints subject to rate limiting:
- Default: 100 requests/minute per API key
- Burst: 200 requests for 10 seconds
- Headers:
  - `X-RateLimit-Limit`: Requests per minute
  - `X-RateLimit-Remaining`: Remaining requests
  - `X-RateLimit-Reset`: Unix timestamp of reset

## Authentication

Use Bearer token in Authorization header:

```
Authorization: Bearer <api_key>
```

API keys provisioned per agent/user. Scopes restrict which endpoints are accessible.

## Webhook Events

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

