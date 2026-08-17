"""Governance demo: sandbox -> quarantine -> approval tiers -> rollback.

Walks through the governance surface end to end:

1. **Sandbox enforcement** — an agent's tool whitelist denies unauthorized
   tools/paths; the third violation auto-quarantines the agent, after which it
   is denied everything until cleared.
2. **Violation clearing** — an operator clears the strikes and the agent
   returns to active.
3. **Self-update approval tiers** — the SelfUpdateGovernor classifies proposals
   into auto / monitored / human review based on trust + risk.
4. **Checkpoint & rollback** — a registry snapshot is checkpointed (SHA-256
   integrity), then verified and rolled back to.

Runs in an isolated repo-root ``data/demo_sandboxes/governance`` directory and
records run metrics in the shared run log; no configuration needed::

    python examples/governance_demo/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from src.agents.summarizer_agent import SummarizerAgent  # noqa: E402
from src.governance.approvals import SelfUpdateGovernor  # noqa: E402
from src.governance.approvals import UpdateProposal
from src.governance.checkpoints import CheckpointStore  # noqa: E402
from src.governance.checkpoints import RollbackManager
from src.integration.agent_registry import AgentRegistry  # noqa: E402
from src.integration.sandbox import AgentSandbox, ToolPolicy  # noqa: E402
from src.runtime_paths import data_path  # noqa: E402
from src.utils.run_logger import init_run_logger  # noqa: E402


def main() -> None:
    """Run the full governance walkthrough."""
    workdir = Path(data_path("demo_sandboxes/governance"))
    workdir.mkdir(parents=True, exist_ok=True)
    run_logger = init_run_logger()
    try:
        print("=" * 70)
        print("ARTEMIS CITY — Governance Demo")
        print("=" * 70)

        registry = AgentRegistry(db_path=str(workdir / "agent_registry.db"))
        agent = SummarizerAgent()
        registry.register_agent(agent)

        _demo_sandbox(registry, agent.name)
        _demo_approvals()
        _demo_checkpoint_rollback(registry, workdir)

        run_logger.finalize_run(
            status="completed",
            summary={"demo": "governance", "data_dir": str(workdir)},
        )
        print(f"\nPersistent demo state: {workdir}")
        print("Done.")
    except Exception as exc:
        run_logger.finalize_run(status="failed", summary={"error": str(exc)})
        raise


def _demo_sandbox(registry: AgentRegistry, agent_name: str) -> None:
    """Show whitelist enforcement and 3-strike quarantine."""
    print("\n[1] Sandbox enforcement & quarantine")
    print("-" * 70)
    sandbox = AgentSandbox(
        agent_name,
        policies=[ToolPolicy("read_file", paths=["Agent Outputs/*"])],
        registry=registry,
    )

    allowed = sandbox.check_action("read_file", path="Agent Outputs/report.md")
    print(f"  read_file Agent Outputs/report.md -> allowed={allowed.allowed}")

    for tool, path in [
        ("delete_file", None),  # tool not whitelisted   (strike 1)
        ("read_file", "/etc/passwd"),  # path not allowed (strike 2)
        ("network_post", None),  # tool not whitelisted   (strike 3 -> quarantine)
    ]:
        res = sandbox.check_action(tool, path=path)
        print(f"  {tool} {path or ''} -> allowed={res.allowed} ({res.violation_type})")

    state = registry.get_governance_state(agent_name)
    print(
        f"  governance state: status={state['status']} "
        f"violations={state['violation_count']}"
    )

    blocked = sandbox.check_action("read_file", path="Agent Outputs/ok.md")
    print(
        f"  post-quarantine read_file -> allowed={blocked.allowed} ({blocked.reason})"
    )

    cleared = registry.clear_violations(agent_name, rationale="reviewed by operator")
    state = registry.get_governance_state(agent_name)
    print(f"  cleared {cleared} violation(s); status now={state['status']}")


def _demo_approvals() -> None:
    """Show the three self-update approval tiers."""
    print("\n[2] Self-update approval tiers")
    print("-" * 70)
    governor = SelfUpdateGovernor()

    cases = [
        (
            "trusted tiny tweak",
            UpdateProposal("agent_a", code_change_ratio=0.005),
            0.95,
        ),
        (
            "medium change",
            UpdateProposal("agent_b", code_change_ratio=0.05, new_dependencies=True),
            0.80,
        ),
        ("breaking change", UpdateProposal("agent_c", breaking_changes=True), 0.95),
    ]
    for label, proposal, trust in cases:
        decision = governor.classify(proposal, trust_score=trust)
        print(
            f"  {label:<20} trust={trust:.2f} -> {decision.tier.value.upper():<9} "
            f"({decision.reasons[0]})"
        )


def _demo_checkpoint_rollback(registry: AgentRegistry, workdir: Path) -> None:
    """Show checkpoint creation, integrity verification, and rollback."""
    print("\n[3] Checkpoint & rollback")
    print("-" * 70)
    store = CheckpointStore(checkpoint_dir=str(workdir / "checkpoints"))
    snapshot = {"agents": registry.get_all_agents_with_scores()}

    record = store.create_checkpoint(
        snapshot, checkpoint_type="manual", metadata={"note": "governance demo"}
    )
    cp_id = record["checkpoint_id"]
    print(
        f"  created checkpoint {cp_id[:8]}… (integrity verified={store.verify_checkpoint(cp_id)})"
    )

    rollback = RollbackManager(store).rollback_to(cp_id, initiated_by="demo_operator")
    restored_agents = rollback["restored_state"].get("agents", [])
    print(
        f"  rollback status={rollback['status']}; "
        f"restored {len(restored_agents)} agent record(s)"
    )


if __name__ == "__main__":
    main()
