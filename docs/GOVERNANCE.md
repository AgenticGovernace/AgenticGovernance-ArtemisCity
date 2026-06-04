# Governance Framework

## Overview

The Artemis City governance system ensures safe, auditable self-updates and runtime policy enforcement. It combines trust-score-based approval tiers, automated testing, sandbox enforcement, and rollback mechanisms to balance autonomy with safety.

## Self-Update Approval Pipeline

### Tier Classification

All updates are classified into three tiers based on risk assessment:

**Tier 1: Auto-Approved**
- Criteria:
  - Code change < 1% of codebase
  - Fully backwards-compatible (no API changes)
  - Only affects performance-non-critical paths
  - Security scan passes (no CVEs, no new dependencies)
  - Trust score agent/component > 0.9
- Approval Process:
  - Automated security scan (pass/fail)
  - Automated testing suite (unit + integration)
  - Deployment on approval (no human intervention)
- Latency: ~5 minutes from submission to live
- Rollback: Available for 30 days

**Tier 2: Monitored**
- Criteria:
  - Code change 1-10% of codebase
  - Backwards-compatible API (additive only)
  - Affects standard execution paths
  - New dependencies require manual review
  - Trust score 0.7-0.9
- Approval Process:
  - Automated security scan (pass/fail)
  - Automated testing (unit, integration, smoke)
  - Human review (domain expert, <24hr SLA)
  - Deployment on human approval
  - Post-deployment monitoring for 24 hours
- Latency: ~24 hours from submission to live
- Rollback: Available for 90 days, auto-rollback on anomalies

**Tier 3: Human**
- Criteria:
  - Code change > 10% of codebase
  - Breaking API changes
  - Policy changes (sandbox rules, approval workflow)
  - New major capabilities
  - Trust score < 0.7 or unknown agent
  - Updates to governance system itself
- Approval Process:
  - Automated security scan (informational)
  - Automated testing (full suite + security tests)
  - Human review (senior engineer + security, <72hr SLA)
  - Staged rollout (canary: 5% → 25% → 100%)
  - Post-deployment monitoring for 7 days
- Latency: ~72 hours from submission to full rollout
- Rollback: Available indefinitely, manual process

### Trust Score Calculation

Each agent/component has a trust score (0.0-1.0) based on:

```
TrustScore = (
  SuccessRate × 0.35 +
  SecurityViolations × -0.25 +
  CodeQualityMetrics × 0.2 +
  AuditApprovals × 0.15 +
  UptimePercentage × 0.05
)

SuccessRate = (SuccessfulExecutions / TotalExecutions) over 30 days
SecurityViolations = max(0, 1 - 0.1 * RecentViolationCount)
CodeQualityMetrics = (CoverageRatio + PassedLints + NoDeadCode) / 3
AuditApprovals = (ApprovedUpdates / TotalUpdateAttempts) over 90 days
UptimePercentage = 1 - (DowntimeHours / TotalHours) over 30 days
```

**Score Decay:**
- Recent actions weighted 2x vs. historical
- Sliding 90-day window for updates
- Violations impact decreases exponentially (half-life: 30 days)

### Update Request Format

```json
{
  "update_id": "uuid",
  "agent_id": "uuid",
  "update_type": "patch|minor|major",
  "changes": {
    "description": "Fix memory leak in task router",
    "files_modified": ["src/kernel.py"],
    "lines_added": 15,
    "lines_deleted": 8,
    "breaking_changes": false,
    "new_dependencies": []
  },
  "metadata": {
    "submitted_at": "2026-02-21T10:30:00Z",
    "submitted_by": "agent_uuid",
    "risk_assessment": {
      "automated_score": "low",
      "tier": 1,
      "rationale": "Performance fix, no API changes"
    }
  },
  "testing": {
    "unit_tests": {
      "passed": 1247,
      "failed": 0,
      "coverage": 0.94
    },
    "integration_tests": {
      "passed": 156,
      "failed": 0
    },
    "security_scan": {
      "status": "passed",
      "cves_detected": 0,
      "new_dependencies": 0
    }
  },
  "rollback_point": {
    "checkpoint_id": "uuid",
    "timestamp": "2026-02-21T10:00:00Z",
    "state_hash": "sha256_hash",
    "verified": true
  }
}
```

### Approval Workflow

```
┌──────────────────┐
│ Update Submitted │
└────────┬─────────┘
         │
    ┌────▼──────────────────┐
    │ Risk Assessment       │
    │ - Code analysis       │
    │ - Determine tier      │
    │ - Trust score check   │
    └────┬──────────────────┘
         │
    ┌────▼────────────────────────────┐
    │ Tier 1: Auto?                   │
    ├────────────────────────────────┤
    │ Y: → Automated Tests → Deploy   │
    │ N: → Continue to Tier 2         │
    └────┬──────────────────┬─────────┘
         │                  │
    ┌────▼──────────────┐   │
    │ Tier 2: Monitored?│   │
    ├──────────────────┤   │
    │ Y: → Human Review │   │
    │ N: → Tier 3       │   │
    └────┬──────────────┘   │
         │                  │
    ┌────▼─────────────────────────────┐
    │ Tier 3: Human Review (Senior)    │
    │ - Manual code review             │
    │ - Security implications          │
    │ - Policy compliance              │
    └────┬──────────┬──────────────────┘
         │          │
      DENY      APPROVE
         │          │
    ┌────▼──┐  ┌────▼──────────────┐
    │Reject │  │ Staged Rollout    │
    │ &Log  │  │ - Canary 5%       │
    └───────┘  │ - Monitor 24h     │
               │ - Ramp 25%        │
               │ - Monitor 24h     │
               │ - Full 100%       │
               └────┬─────────────┘
                    │
               ┌────▼───────────────┐
               │ Post-Deployment    │
               │ Monitoring (7 days)│
               └────┬──────────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
       ┌──▼────────┐    ┌────▼───────┐
       │Anomalies? │    │Success?     │
       │Y: Rollback│    │Y: Complete  │
       │N: Continue│    │N: Investigate
       └───────────┘    └─────────────┘
```

## Sandbox Enforcement

### Tool Whitelisting

Each agent has an approved tool list:

```json
{
  "agent_id": "uuid",
  "tools_whitelist": [
    {
      "tool_name": "file_read",
      "paths": ["/data/public/**", "/tmp/**"],
      "operations": ["read"],
      "rate_limit": 100,
      "rate_window_seconds": 60
    },
    {
      "tool_name": "vector_search",
      "parameters": {
        "max_results": 100,
        "min_similarity": 0.3
      },
      "rate_limit": 50,
      "rate_window_seconds": 60
    }
  ]
}
```

### Permission Checks

**File Access:**
- Path must match whitelist pattern
- Operation (read/write/delete) must be approved
- File size limits enforced (default: 100MB)
- Audit log: timestamp, agent_id, path, operation, result

**Network Access:**
- Domain must be in allowlist or match regex pattern
- Port whitelist (default: 443, 80)
- Rate limiting per domain (default: 10 req/min)
- Audit log: timestamp, agent_id, domain, port, status

**Capability Requirements:**
- Agent must have capability tag for tool usage
- Example: tool "code-execution" requires capability "code-runner"

### Violation Handling

**Violation Detection:**
- Unauthorized tool invocation
- Path outside whitelist
- Rate limit exceeded
- Missing capability tag
- Unsafe network destination

**Per-Violation Response:**
```
Violation 1: Log incident, allow operation (with warning)
Violation 2: Log incident, allow operation (with warning)
Violation 3: QUARANTINE agent immediately
  ├─ Prevent new task assignments
  ├─ In-flight tasks allowed to complete
  ├─ Flag status as "quarantined" in Registry
  └─ Require manual override (trust tier upgrade)
```

**Violation Log Schema:**
```json
{
  "violation_id": "uuid",
  "timestamp": "2026-02-21T10:30:00Z",
  "agent_id": "uuid",
  "violation_type": "unauthorized_tool|unauthorized_path|rate_limit|missing_capability",
  "details": {
    "tool_name": "file_read",
    "requested_path": "/etc/passwd",
    "allowed_paths": ["/data/public/**"]
  },
  "agent_violation_count": 3,
  "action_taken": "quarantine",
  "quarantine_until": null,
  "manual_override_required": true
}
```

### Quarantine Management

**Manual Override:**
```json
{
  "override_id": "uuid",
  "agent_id": "uuid",
  "action": "upgrade_trust_tier|temporary_clearance",
  "new_tier": "monitored",
  "duration_minutes": null,
  "approved_by": "admin_uuid",
  "rationale": "Manual review confirms safe behavior",
  "timestamp": "2026-02-21T11:00:00Z"
}
```

**Quarantine Recovery:**
- Automatic after 7 days if no new violations
- Manual after review by senior engineer
- Requires trust score > 0.7 for auto-approval

## Rollback Mechanism

### Checkpoint Strategy

Checkpoints created at safe points:
- Successful deployment completion
- Before each major configuration change
- On-demand by administrator
- Automatically at scheduled intervals (daily)

**Checkpoint Structure:**
```json
{
  "checkpoint_id": "uuid",
  "timestamp": "2026-02-21T10:00:00Z",
  "type": "deployment|scheduled|manual",
  "metadata": {
    "deployed_version": "1.2.3",
    "affected_components": ["kernel", "memory_bus"],
    "affected_agents": ["agent_uuid_1", "agent_uuid_2"]
  },
  "state": {
    "system_hash": "sha256_hash",
    "config_hash": "sha256_hash",
    "registry_snapshot": "encoded_json"
  },
  "retention": {
    "expires_at": "2026-04-21T10:00:00Z",
    "days_retained": 60,
    "locked_until": null
  },
  "verified": true
}
```

### Rollback Execution

**Tier 1/2 Rollback (Automated):**
```
1. Validate rollback point integrity
2. Stop affected agents gracefully
3. Restore system state from checkpoint
4. Verify system health (unit tests, core functions)
5. Resume agents incrementally
6. Monitor for 1 hour
7. Log rollback with details
```

**Tier 3 Rollback (Manual + Staged):**
```
1. Senior engineer initiates rollback
2. Automated validation
3. Canary rollback (5% of traffic)
4. Monitor 2 hours
5. Expand to 25%, monitor 2 hours
6. Full rollback if all stable
7. Post-rollback analysis
8. Root cause investigation
```

**Rollback Request:**
```json
{
  "rollback_id": "uuid",
  "checkpoint_id": "uuid",
  "initiated_by": "agent_uuid|admin_uuid",
  "reason": "error_detected|manual_request",
  "details": "Anomaly: error rate > 5%",
  "timestamp": "2026-02-21T10:35:00Z"
}
```

## Policy Enforcement

### Sandbox Policy Updates

When sandbox policies are updated:

1. **Validation Phase:**
   - Verify policy syntax
   - Check for conflicts (agent capabilities vs. restrictions)
   - Simulate on test agent

2. **Approval Phase:**
   - Tier 2+ governance (trust tier required for broad policies)
   - Human review if affects high-capability agents

3. **Deployment Phase:**
   - Announce change to all agents
   - Apply new policy at enforcement point
   - Log policy version in each sandboxed operation

4. **Compliance Check:**
   - Periodic audit of agent behavior vs. policy
   - Flag policy-violating activities as violations

### Capability Management

**Capability Addition:**
```json
{
  "operation": "add_capability",
  "agent_id": "uuid",
  "capability": "advanced_code_execution",
  "approval_required": true,
  "requires_tier": 3,
  "sandbox_rules": {
    "memory_limit_mb": 2048,
    "timeout_seconds": 300,
    "file_paths": ["/tmp/**"],
    "network_access": ["localhost"]
  }
}
```

**Capability Removal:**
- Immediate on violation threshold
- Gradual deprecation for planned removals (30-day notice)
- Audit trail of all capability changes

## Monitoring & Alerts

### Governance Metrics

```
artemis_governance_approval_latency_seconds (histogram)
  Labels: tier, approval_status

artemis_governance_tier_distribution (gauge)
  Labels: tier, approval_status

artemis_sandbox_violations_total (counter)
  Labels: agent_id, violation_type, action_taken

artemis_sandbox_quarantined_agents (gauge)
  Current count of quarantined agents

artemis_rollback_count (counter)
  Labels: tier, initiated_by, reason

artemis_trust_score (gauge)
  Labels: agent_id
  Current trust score (0.0-1.0)
```

### Alert Thresholds

| Alert | Threshold | Action |
|-------|-----------|--------|
| High violation rate | >2 violations/hour/agent | Page oncall |
| Tier 3 stuck | No approval >96h | Escalate to manager |
| Rollback frequency | >2 rollbacks/week | Performance review |
| Trust score drop | >0.2 in 24h | Alert security team |
| Sandbox escape attempt | Any detected | Page security |

## Configuration

### Environment Variables

```bash
ARTEMIS_APPROVAL_TIER1_ENABLED=true
ARTEMIS_APPROVAL_TIER2_TIMEOUT_HOURS=24
ARTEMIS_APPROVAL_TIER3_TIMEOUT_HOURS=72
ARTEMIS_AUTO_ROLLBACK_ON_ERRORS=true
ARTEMIS_AUTO_ROLLBACK_ERROR_THRESHOLD=0.05  # 5%
ARTEMIS_SANDBOX_VIOLATION_QUARANTINE_COUNT=3
ARTEMIS_SANDBOX_VIOLATION_DECAY_DAYS=30
ARTEMIS_CHECKPOINT_RETENTION_DAYS=60
ARTEMIS_TRUST_SCORE_UPDATE_INTERVAL_MINUTES=15
```

## Governance Best Practices

1. **Always create checkpoints** before Tier 2+ deployments
2. **Test rollback procedures** monthly (chaos engineering)
3. **Review trust scores** weekly for drift
4. **Audit sandbox violations** monthly
5. **Rotate approval authorities** quarterly
6. **Maintain policy documentation** in version control
7. **Run post-mortems** on all rollbacks and Tier 3 rejections

