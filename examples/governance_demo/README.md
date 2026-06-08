# Governance Demo

End-to-end tour of the governance surface: runtime sandboxing, trust-based
approval tiers, and checkpoint/rollback.

```bash
python examples/governance_demo/run.py
```

## What it does

1. **Sandbox enforcement** — registers an agent with a tool whitelist
   (`ToolPolicy`), then issues actions through an `AgentSandbox`:
   - an allowed `read_file` within the permitted path,
   - three denied actions (unauthorized tool, unauthorized path, unauthorized
     tool) — the **third strike auto-quarantines** the agent via the registry.
   - once quarantined, every action is denied until cleared.
2. **Violation clearing** — an operator calls `clear_violations(...)` and the
   agent returns to `active`.
3. **Approval tiers** — `SelfUpdateGovernor.classify(...)` sorts three sample
   proposals into `AUTO`, `MONITORED`, and `HUMAN` based on trust + risk.
4. **Checkpoint & rollback** — snapshots the registry into a `CheckpointStore`
   (SHA-256 integrity hash), verifies it, and rolls back via `RollbackManager`.

All state lives in a temporary directory that is removed on exit.

## Expected output (abridged)

```
[1] Sandbox enforcement & quarantine
  read_file Agent Outputs/report.md -> allowed=True
  delete_file  -> allowed=False (unauthorized_tool)
  read_file /etc/passwd -> allowed=False (unauthorized_path)
  network_post  -> allowed=False (unauthorized_tool)
  governance state: status=quarantined violations=3
  post-quarantine read_file -> allowed=False (agent is quarantined)
  cleared 3 violation(s); status now=active

[2] Self-update approval tiers
  trusted tiny tweak   trust=0.95 -> AUTO
  medium change        trust=0.80 -> MONITORED
  breaking change      trust=0.95 -> HUMAN

[3] Checkpoint & rollback
  created checkpoint a1b2c3d4… (integrity verified=True)
  rollback status=verified; restored 1 agent record(s)
```
