# Artemis City Architecture

## Overview

Artemis City is a multi-agent operating system designed for autonomous task orchestration with adaptive learning and governance. The system combines distributed task routing, semantic memory persistence, Hebbian learning, and sandbox-based security into a cohesive framework.

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
Score = (Alignment × 0.4) + (Accuracy × 0.35) + (Efficiency × 0.25)
WeightedScore = Score × HebianWeight(agent, task_type)
```

**Key Behaviors:**
- Fallback routing if primary agent unavailable
- Load balancing across agents with similar scores
- Timeout enforcement (configurable per task class)
- Retry logic with exponential backoff

### 2. Memory Bus

The Memory Bus provides unified access to both explicit (Obsidian) and semantic (vector store) memory with write-through synchronization.

**Architecture:**
```
┌─────────────────────────────────────────┐
│          Kernel / Agents                │
└────────────────┬────────────────────────┘
                 │ Read/Write
       ┌─────────▼─────────┐
       │   Memory Bus      │
       │  (Coordinator)    │
       └────┬──────────┬───┘
            │          │
      ┌─────▼─┐   ┌───▼─────┐
      │Obsidian│   │ Vector  │
      │ Store  │   │  Store  │
      └────────┘   └─────────┘
```

**Read Hierarchy:**
1. **Exact Match**: Direct Obsidian lookup (latency: <50ms)
2. **Keyword Match**: Obsidian metadata search (latency: <150ms)
3. **Semantic Match**: Vector similarity search (latency: <300ms)

**Write Protocol (Write-Through):**
- All writes route through Memory Bus coordinator
- Synchronous write to Obsidian (primary store)
- Asynchronous propagation to vector store (with 200ms p95 SLA)
- Dual-confirmation before acknowledging write
- Conflict resolution via timestamp + content hash

**Latency SLAs:**
- Write latency p95: <200ms
- Sync propagation lag p95: <300ms
- Read exact match p99: <100ms
- Read semantic p99: <500ms

### 3. Hebbian Learning Layer

Adaptive connection strength between agents and task types through Hebbian weighting.

**Mechanism:**
- Weight matrix: Agent × Task Type
- Initial weight: 0.5 (neutral)
- Increment: +1 for successful completion
- Decrement: -1 for failure
- Decay: 5% every 30 days

**Storage Backend:**
- SQLite-backed persistence
- Atomic updates via transactions
- Automatic archival at 180 days
- Deletion threshold: weights < 0.01

**Propagation:**
- Batched updates every 60 seconds
- Synced to Obsidian frontmatter (metadata)
- Indexed in vector store for semantic correlation

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
    │  - Rank by Hebbian    │
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
    │  - +1/-1 weight       │
    │  - Batched sync       │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Memory Persistence   │
    │  - Write-through      │
    │  - Update Vector DB   │
    └────┬──────────────────┘
         │
    ┌────▼──────────────────┐
    │  Return Result        │
    └───────────────────────┘
```

## Integration Points

**Obsidian Integration:**
- YAML frontmatter stores Hebbian weights and metadata
- Bidirectional sync via Memory Bus
- Full-text search via Obsidian plugins

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

- **Write-Through**: All data synchronized before acknowledgment
- **Eventual Consistency**: Vector store index updates within 300ms (p95)
- **Durability**: Obsidian + Vector Store provide redundant storage
- **Atomicity**: Per-task execution is all-or-nothing via transactions

## Performance Targets

| Operation | p50 | p95 | p99 |
|-----------|-----|-----|-----|
| Task routing | 5ms | 15ms | 30ms |
| Agent lookup | 2ms | 8ms | 20ms |
| Memory write | 50ms | 200ms | 400ms |
| Memory read (exact) | 10ms | 50ms | 100ms |
| Memory read (vector) | 100ms | 300ms | 500ms |
| Hebbian update | 1ms | 5ms | 10ms |
| Sandbox check | 2ms | 10ms | 20ms |

## Failure Modes & Recovery

**Agent Timeout:**
- Abort task after threshold
- Decrement accuracy score
- Auto-retry on next invocation (agent-dependent)

**Memory Bus Desynchronization:**
- Detect via consistency checks
- Trigger rebuild from Obsidian source-of-truth
- Alert monitoring system

**Sandbox Violation:**
- Log violation with context
- Increment violation counter
- Quarantine on 3rd violation
- Prevent further execution pending review

**Registry Unavailability:**
- Cache recent agent metadata
- Degrade to pre-computed rankings
- Queued requests until recovery

