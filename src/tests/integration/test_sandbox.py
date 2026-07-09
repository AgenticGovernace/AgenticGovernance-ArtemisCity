"""Integration tests for AgentSandbox.

Tests the ``AgentSandbox``, ``ToolPolicy``, and ``CheckResult`` classes from
``src.integration.sandbox``.
"""

import sys
from pathlib import Path

_repo = str(Path(__file__).resolve().parents[3])
if _repo not in sys.path:
    sys.path.insert(0, _repo)
for _key in [k for k in sys.modules if k == "integration" or k.startswith("integration.")]:
    del sys.modules[_key]

import pytest
from src.integration.sandbox import (
    AgentSandbox,
    ToolPolicy,
    CheckResult,
    VIOLATION_UNAUTHORIZED_TOOL,
    VIOLATION_UNAUTHORIZED_PATH,
    VIOLATION_UNAUTHORIZED_OPERATION,
)


class TestToolPolicy:
    """Tests for ToolPolicy dataclass."""

    def test_allows_any_path_by_default(self):
        """Empty paths list allows any path."""
        policy = ToolPolicy(name="file_read")
        assert policy.allows_path("/etc/passwd") is True
        assert policy.allows_path("/home/user/data.txt") is True

    def test_allows_matching_path_glob(self):
        """Path matching via glob patterns."""
        policy = ToolPolicy(name="file_read", paths=["/vault/*"])
        assert policy.allows_path("/vault/note.md") is True
        assert policy.allows_path("/etc/passwd") is False

    def test_allows_any_operation_by_default(self):
        """Empty operations list allows any operation."""
        policy = ToolPolicy(name="memory_write")
        assert policy.allows_operation("create") is True
        assert policy.allows_operation(None) is True

    def test_restricts_operations(self):
        """Only listed operations are allowed."""
        policy = ToolPolicy(name="memory_write", operations=["read", "list"])
        assert policy.allows_operation("read") is True
        assert policy.allows_operation("delete") is False


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_allowed(self):
        r = CheckResult(allowed=True)
        assert r.allowed is True
        assert r.violation_type is None

    def test_denied(self):
        r = CheckResult(allowed=False, violation_type="unauthorized_tool", reason="not whitelisted")
        assert r.allowed is False
        assert r.violation_type == "unauthorized_tool"


class TestAgentSandbox:
    """Tests for AgentSandbox class."""

    @pytest.fixture
    def sandbox(self):
        """Create a sandbox with a small whitelist, no registry."""
        policies = [
            ToolPolicy(name="file_read", paths=["/vault/*"]),
            ToolPolicy(name="memory_read"),
            ToolPolicy(name="memory_write", operations=["create", "update"]),
        ]
        return AgentSandbox(agent_name="test_agent_1", policies=policies)

    def test_sandbox_initialization(self, sandbox):
        """Test sandbox is initialized correctly."""
        assert sandbox.agent_name == "test_agent_1"
        assert "file_read" in sandbox.policies
        assert "memory_read" in sandbox.policies

    def test_allowed_action(self, sandbox):
        """Test that whitelisted tool is permitted."""
        result = sandbox.check_action("memory_read")
        assert result.allowed is True

    def test_allowed_action_with_path(self, sandbox):
        """Whitelisted tool + matching path is allowed."""
        result = sandbox.check_action("file_read", path="/vault/note.md")
        assert result.allowed is True

    def test_denied_tool_not_whitelisted(self, sandbox):
        """Non-whitelisted tools are denied."""
        result = sandbox.check_action("shell_execute")
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_TOOL

    def test_denied_file_access_outside_scope(self, sandbox):
        """File access outside allowed paths is denied."""
        result = sandbox.check_action("file_read", path="/etc/passwd")
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_PATH

    def test_denied_operation_not_allowed(self, sandbox):
        """Operations not in the policy's list are denied."""
        result = sandbox.check_action("memory_write", operation="delete")
        assert result.allowed is False
        assert result.violation_type == VIOLATION_UNAUTHORIZED_OPERATION

    def test_allowed_operation(self, sandbox):
        """Operations matching the policy are allowed."""
        result = sandbox.check_action("memory_write", operation="create")
        assert result.allowed is True

    def test_quarantined_agent_denied(self):
        """A quarantined agent is denied all actions."""

        class _MockRegistry:
            def is_quarantined(self, name):
                return True

            def record_violation(self, *args, **kwargs):
                pass

        sandbox = AgentSandbox(
            agent_name="bad_agent",
            policies=[ToolPolicy(name="file_read")],
            registry=_MockRegistry(),
        )
        result = sandbox.check_action("file_read")
        assert result.allowed is False
        assert result.reason == "agent is quarantined"

    def test_violation_recorded_in_registry(self):
        """Denied actions are recorded via the registry."""
        violations = []

        class _MockRegistry:
            def is_quarantined(self, name):
                return False

            def record_violation(self, agent_name, vtype, details):
                violations.append((agent_name, vtype))

        sandbox = AgentSandbox(
            agent_name="agent_x",
            policies=[],
            registry=_MockRegistry(),
        )
        sandbox.check_action("shell_execute")
        assert len(violations) == 1
        assert violations[0] == ("agent_x", VIOLATION_UNAUTHORIZED_TOOL)

    def test_no_registry_still_works(self):
        """Sandbox without a registry still denies but doesn't crash."""
        sandbox = AgentSandbox(agent_name="solo", policies=[])
        result = sandbox.check_action("file_read")
        assert result.allowed is False

    def test_multiple_policies(self):
        """Multiple policies are checked independently."""
        policies = [
            ToolPolicy(name="file_read"),
            ToolPolicy(name="file_write"),
            ToolPolicy(name="memory_read"),
        ]
        sandbox = AgentSandbox(agent_name="multi", policies=policies)
        assert sandbox.check_action("file_read").allowed is True
        assert sandbox.check_action("file_write").allowed is True
        assert sandbox.check_action("memory_read").allowed is True
        assert sandbox.check_action("shell_execute").allowed is False
