"""Contracts for local and protected environment automation hooks."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_make_targets_and_local_hooks_split_source_fix_from_live_checks() -> None:
    """Pre-commit repairs deterministic sources; pre-push checks live state."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    config = yaml.safe_load(
        (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    local_repo = next(item for item in config["repos"] if item["repo"] == "local")
    hooks = {hook["id"]: hook for hook in local_repo["hooks"]}

    assert "env-check:" in makefile
    assert "env-fix:" in makefile
    assert "env-live-check:" in makefile
    assert "--hook-type pre-push" in makefile
    assert hooks["environment-contract-fix"]["stages"] == ["pre-commit"]
    assert hooks["environment-live-check"]["stages"] == ["pre-push"]
    assert hooks["environment-contract-fix"]["pass_filenames"] is False
    assert hooks["environment-live-check"]["pass_filenames"] is False


def test_promotion_uses_source_gate_then_protected_staging_and_prod_live_gates() -> (
    None
):
    """PRs stay offline while promotions inherit GitHub Environment protection."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/promote.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    test_steps = {step.get("name"): step for step in jobs["test"]["steps"]}

    assert test_steps["Validate environment source contract"]["run"] == (
        "make env-check"
    )
    assert jobs["staging-live"]["environment"] == "staging"
    assert jobs["prod-live"]["environment"] == "prod"
    assert jobs["staging-live"]["if"] == "github.event_name != 'pull_request'"
    assert "staging-live" in jobs["promote-staging"]["needs"]
    assert jobs["prod-live"]["needs"] == ["resolve", "promote-staging"]
    assert "prod-live" in jobs["promote-prod"]["needs"]
