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
    """Registry.
    
    Args:
        tmp_path: Tmp path value used by this operation.
    
    Returns:
        None: This function does not return a value.
    """
    reg = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    reg.register_agent(_StubAgent("Alpha", capabilities=["research"]))
    return reg


@pytest.fixture
def sandbox(registry):
    """Sandbox.
    
    Args:
        registry: Agent registry used to persist and read governance state.
    
    Returns:
        None: This function does not return a value.
    """
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
    """Provide the TestAllowed abstraction used by this module.
    """
    def test_whitelisted_tool_allowed(self, sandbox):
        """Test that whitelisted tool allowed.
        
        Args:
            sandbox: Sandbox value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        result = sandbox.check_action("vector_search")
        assert result.allowed is True
        assert result.violation_type is None

    def test_allowed_path_and_op(self, sandbox):
        """Test that allowed path and op.
        
        Args:
            sandbox: Sandbox value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        result = sandbox.check_action(
            "file_read", path="/data/public/doc.md", operation="read"
        )
        assert result.allowed is True

    def test_unconstrained_tool_allows_any_path(self, sandbox):
        """Test that unconstrained tool allows any path.
        
        Args:
            sandbox: Sandbox value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        result = sandbox.check_action("vector_search", path="/anywhere")
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Denials record violations
# ---------------------------------------------------------------------------
class TestDenied:
    """Provide the TestDenied abstraction used by this module.
    """
    def test_unknown_tool_denied_and_recorded(self, sandbox, registry):
        """Test that unknown tool denied and recorded.
        
        Args:
            sandbox: Sandbox value used by this operation.
            registry: Agent registry used to persist and read governance state.
        
        Returns:
            None: This function does not return a value.
        """
        result = sandbox.check_action("delete_everything")
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_TOOL
        assert registry.get_governance_state("Alpha")["violation_count"] == 1

    def test_path_outside_whitelist_denied(self, sandbox, registry):
        """Test that path outside whitelist denied.
        
        Args:
            sandbox: Sandbox value used by this operation.
            registry: Agent registry used to persist and read governance state.
        
        Returns:
            None: This function does not return a value.
        """
        result = sandbox.check_action(
            "file_read", path="/etc/passwd", operation="read"
        )
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_PATH
        assert registry.get_governance_state("Alpha")["violation_count"] == 1

    def test_disallowed_operation_denied(self, sandbox):
        """Test that disallowed operation denied.
        
        Args:
            sandbox: Sandbox value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        result = sandbox.check_action(
            "file_read", path="/tmp/x", operation="write"
        )
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_PATH


# ---------------------------------------------------------------------------
# Integration with quarantine
# ---------------------------------------------------------------------------
class TestQuarantineIntegration:
    """Provide the TestQuarantineIntegration abstraction used by this module.
    """
    def test_three_denials_quarantine(self, sandbox, registry):
        """Test that three denials quarantine.
        
        Args:
            sandbox: Sandbox value used by this operation.
            registry: Agent registry used to persist and read governance state.
        
        Returns:
            None: This function does not return a value.
        """
        for _ in range(QUARANTINE_THRESHOLD):
            sandbox.check_action("bad_tool")
        assert registry.is_quarantined("Alpha") is True

    def test_quarantined_agent_denied_everything(self, sandbox, registry):
        """Test that quarantined agent denied everything.
        
        Args:
            sandbox: Sandbox value used by this operation.
            registry: Agent registry used to persist and read governance state.
        
        Returns:
            None: This function does not return a value.
        """
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
    """Provide the TestNoRegistry abstraction used by this module.
    """
    def test_enforces_without_recording(self):
        """Test that enforces without recording.
        
        Returns:
            None: This function does not return a value.
        """
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
    """Provide the TestToolPolicy abstraction used by this module.
    """
    def test_glob_match(self):
        """Test that glob match.
        
        Returns:
            None: This function does not return a value.
        """
        p = ToolPolicy(name="f", paths=["/a/**"])
        assert p.allows_path("/a/b/c") is True
        assert p.allows_path("/b/c") is False

    def test_empty_paths_allows_all(self):
        """Test that empty paths allows all.
        
        Returns:
            None: This function does not return a value.
        """
        assert ToolPolicy(name="f").allows_path("/anything") is True

    def test_operation_constraint(self):
        """Test that operation constraint.
        
        Returns:
            None: This function does not return a value.
        """
        p = ToolPolicy(name="f", operations=["read"])
        assert p.allows_operation("read") is True
        assert p.allows_operation("write") is False
        assert ToolPolicy(name="f").allows_operation("write") is True
