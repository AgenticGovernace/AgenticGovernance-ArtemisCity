"""Tests for the agent sandbox enforcement layer."""

import pytest
from src.agents.base_agent import BaseAgent
from src.integration.agent_registry import AgentRegistry, QUARANTINE_THRESHOLD
from src.integration.sandbox import (
    AgentSandbox,
    ToolPolicy,
    VIOLATION_UNAUTHORIZED_PATH,
    VIOLATION_UNAUTHORIZED_TOOL,
)


class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success"}


@pytest.fixture
def registry(tmp_path):
    reg = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    reg.register_agent(_StubAgent("Alpha", capabilities=["research"]))
    return reg


@pytest.fixture
def sandbox(registry):
    policies = [
        ToolPolicy(
            name="file_read",
            paths=["/data/public/**", "/tmp/**"],
            operations=["read"],
        ),
        ToolPolicy(name="vector_search"),  # unconstrained
    ]
    return AgentSandbox("Alpha", policies=policies, registry=registry)


# ---------------------------------------------------------------------------
# Allow paths
# ---------------------------------------------------------------------------
class TestAllowed:
    def test_whitelisted_tool_allowed(self, sandbox):
        result = sandbox.check_action("vector_search")
        assert result.allowed is True
        assert result.violation_type is None

    def test_allowed_path_and_op(self, sandbox):
        result = sandbox.check_action(
            "file_read", path="/data/public/doc.md", operation="read"
        )
        assert result.allowed is True

    def test_unconstrained_tool_allows_any_path(self, sandbox):
        result = sandbox.check_action("vector_search", path="/anywhere")
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Denials record violations
# ---------------------------------------------------------------------------
class TestDenied:
    def test_unknown_tool_denied_and_recorded(self, sandbox, registry):
        result = sandbox.check_action("delete_everything")
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_TOOL
        assert registry.get_governance_state("Alpha")["violation_count"] == 1

    def test_path_outside_whitelist_denied(self, sandbox, registry):
        result = sandbox.check_action(
            "file_read", path="/etc/passwd", operation="read"
        )
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_PATH
        assert registry.get_governance_state("Alpha")["violation_count"] == 1

    def test_disallowed_operation_denied(self, sandbox):
        result = sandbox.check_action(
            "file_read", path="/tmp/x", operation="write"
        )
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_PATH


# ---------------------------------------------------------------------------
# Integration with quarantine
# ---------------------------------------------------------------------------
class TestQuarantineIntegration:
    def test_three_denials_quarantine(self, sandbox, registry):
        for _ in range(QUARANTINE_THRESHOLD):
            sandbox.check_action("bad_tool")
        assert registry.is_quarantined("Alpha") is True

    def test_quarantined_agent_denied_everything(self, sandbox, registry):
        for _ in range(QUARANTINE_THRESHOLD):
            sandbox.check_action("bad_tool")
        # Even a normally-allowed tool is now denied.
        result = sandbox.check_action("vector_search")
        assert result.allowed is False
        assert "quarantined" in result.reason


# ---------------------------------------------------------------------------
# Sandbox without a registry (isolated unit use)
# ---------------------------------------------------------------------------
class TestNoRegistry:
    def test_enforces_without_recording(self):
        sandbox = AgentSandbox(
            "Solo", policies=[ToolPolicy(name="ping")], registry=None
        )
        assert sandbox.check_action("ping").allowed is True
        denied = sandbox.check_action("nope")
        assert denied.allowed is False
        assert denied.violation_type == VIOLATION_UNAUTHORIZED_TOOL


# ---------------------------------------------------------------------------
# ToolPolicy helpers
# ---------------------------------------------------------------------------
class TestToolPolicy:
    def test_glob_match(self):
        p = ToolPolicy(name="f", paths=["/a/**"])
        assert p.allows_path("/a/b/c") is True
        assert p.allows_path("/b/c") is False

    def test_empty_paths_allows_all(self):
        assert ToolPolicy(name="f").allows_path("/anything") is True

    def test_operation_constraint(self):
        p = ToolPolicy(name="f", operations=["read"])
        assert p.allows_operation("read") is True
        assert p.allows_operation("write") is False
        assert ToolPolicy(name="f").allows_operation("write") is True
