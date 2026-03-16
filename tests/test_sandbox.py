"""Integration tests for AgentSandbox and SandboxManager."""

import sys
from pathlib import Path

# The repo root has a duplicate `integration/` package that shadows
# `src/integration/` when pytest adds '.' to sys.path.  Force resolution
# from src/ by flushing any cached root-level integration import.
_src = str(Path(__file__).resolve().parents[2] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
else:
    sys.path.remove(_src)
    sys.path.insert(0, _src)
# Remove stale cache entry so Python re-discovers from src/
for _key in [
    k for k in sys.modules if k == "integration" or k.startswith("integration.")
]:
    del sys.modules[_key]

import pytest

from integration.sandbox import (
    AgentSandbox,
    QuarantineStatus,
    SandboxManager,
    ViolationSeverity,
    ViolationType,
)


class TestAgentSandbox:
    """Tests for AgentSandbox class."""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """Create a sandbox instance for testing."""
        return AgentSandbox(
            agent_id="test_agent_1",
            tool_whitelist={"file_read", "memory_read", "memory_write"},
            allowed_paths=[str(tmp_path)],
            log_dir=str(tmp_path / "sandbox_logs"),
        )

    def test_sandbox_initialization(self, sandbox):
        """Test sandbox is initialized correctly."""
        assert sandbox.agent_id == "test_agent_1"
        assert sandbox.status == QuarantineStatus.ACTIVE
        assert "file_read" in sandbox.tool_whitelist
        assert len(sandbox.violation_log) == 0

    def test_allowed_action(self, sandbox, tmp_path):
        """Test that whitelisted actions are permitted."""
        test_file = tmp_path / "data.txt"
        test_file.touch()
        assert sandbox.check_action("file_read", str(test_file)) is True

    def test_denied_tool_not_whitelisted(self, sandbox):
        """Test that non-whitelisted tools are denied."""
        result = sandbox.check_action("shell_execute", "/bin/bash")
        assert result is False
        assert len(sandbox.violation_log) == 1
        assert (
            sandbox.violation_log[0].violation_type
            == ViolationType.TOOL_NOT_WHITELISTED
        )

    def test_denied_file_access_outside_scope(self, sandbox):
        """Test that file access outside allowed paths is denied."""
        result = sandbox.check_action("file_read", "/etc/passwd")
        assert result is False
        assert len(sandbox.violation_log) == 1
        assert (
            sandbox.violation_log[0].violation_type
            == ViolationType.UNAUTHORIZED_FILE_ACCESS
        )

    def test_quarantine_after_threshold(self, sandbox):
        """Test auto-quarantine after 3 violations in the window."""
        sandbox.check_action("shell_execute", "cmd1")
        sandbox.check_action("network_request", "cmd2")
        sandbox.check_action("api_call", "cmd3")
        assert sandbox.status == QuarantineStatus.QUARANTINED

    def test_quarantined_agent_denied(self, sandbox):
        """Test that quarantined agents are denied all actions."""
        # Force quarantine
        sandbox.check_action("shell_execute", "x")
        sandbox.check_action("shell_execute", "x")
        sandbox.check_action("shell_execute", "x")
        assert sandbox.status == QuarantineStatus.QUARANTINED

        # Even a whitelisted action should be denied
        result = sandbox.check_action("file_read", "/tmp/ok.txt")
        assert result is False

    def test_release_from_quarantine(self, sandbox):
        """Test releasing an agent from quarantine."""
        sandbox.check_action("shell_execute", "x")
        sandbox.check_action("shell_execute", "x")
        sandbox.check_action("shell_execute", "x")
        assert sandbox.status == QuarantineStatus.QUARANTINED

        sandbox.release_from_quarantine(authorized_by="admin")
        assert sandbox.status == QuarantineStatus.ACTIVE

    def test_alignment_impact(self, sandbox):
        """Test cumulative alignment score impact from violations."""
        sandbox.check_action("shell_execute", "x")  # MEDIUM: -0.05
        impact = sandbox.get_alignment_impact()
        assert impact == pytest.approx(-0.05, abs=0.001)

    def test_violation_summary(self, sandbox):
        """Test structured violation summary output."""
        sandbox.check_action("shell_execute", "x")
        summary = sandbox.get_violation_summary()
        assert summary["agent_id"] == "test_agent_1"
        assert summary["total_violations"] == 1
        assert summary["status"] == "active"

    def test_violations_in_window(self, sandbox):
        """Test the rolling window violation counter."""
        sandbox.check_action("shell_execute", "x")
        sandbox.check_action("shell_execute", "y")
        assert sandbox.violations_in_window == 2


class TestSandboxManager:
    """Tests for SandboxManager class."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SandboxManager instance for testing."""
        return SandboxManager(log_dir=str(tmp_path / "sandbox_logs"))

    def test_manager_initialization(self, manager):
        """Test manager is initialized correctly."""
        assert isinstance(manager.sandboxes, dict)
        assert len(manager.sandboxes) == 0

    def test_create_sandbox(self, manager):
        """Test creating a new sandbox."""
        sandbox = manager.create_sandbox("agent_1", role="researcher")
        assert "agent_1" in manager.sandboxes
        assert sandbox.agent_id == "agent_1"
        assert "file_read" in sandbox.tool_whitelist

    def test_create_sandbox_with_custom_whitelist(self, manager):
        """Test creating a sandbox with custom permissions."""
        sandbox = manager.create_sandbox(
            "agent_2",
            custom_whitelist={"file_read", "file_write"},
        )
        assert sandbox.tool_whitelist == {"file_read", "file_write"}

    def test_check_agent_action(self, manager):
        """Test checking actions through the manager."""
        manager.create_sandbox("agent_3", role="summarizer")
        assert manager.check_agent_action("agent_3", "file_read") is True
        assert manager.check_agent_action("agent_3", "shell_execute") is False

    def test_check_unknown_agent_denied(self, manager):
        """Test that unknown agents are denied."""
        assert manager.check_agent_action("unknown_agent", "file_read") is False

    def test_get_quarantined_agents(self, manager):
        """Test listing quarantined agents."""
        sandbox = manager.create_sandbox(
            "bad_agent",
            custom_whitelist=set(),  # Empty whitelist = everything denied
        )
        # Trigger 3 violations
        sandbox.check_action("file_read", "x")
        sandbox.check_action("file_read", "y")
        sandbox.check_action("file_read", "z")

        quarantined = manager.get_quarantined_agents()
        assert "bad_agent" in quarantined

    def test_get_all_violations(self, manager):
        """Test aggregating violations across all sandboxes."""
        sb1 = manager.create_sandbox("a1", custom_whitelist=set())
        sb2 = manager.create_sandbox("a2", custom_whitelist=set())
        sb1.check_action("x", "")
        sb2.check_action("y", "")

        violations = manager.get_all_violations()
        assert len(violations) == 2

    def test_system_health(self, manager):
        """Test aggregate health metrics."""
        manager.create_sandbox("agent_ok", role="researcher")
        sb = manager.create_sandbox("agent_bad", custom_whitelist=set())
        sb.check_action("x", "")
        sb.check_action("y", "")
        sb.check_action("z", "")

        health = manager.get_system_health()
        assert health["total_agents"] == 2
        assert health["quarantined_agents"] == 1
        assert health["active_agents"] == 1

    def test_default_whitelists_by_role(self, manager):
        """Test that different roles get different default permissions."""
        researcher = manager.create_sandbox("r1", role="researcher")
        summarizer = manager.create_sandbox("s1", role="summarizer")
        cli = manager.create_sandbox("c1", role="cli_agent")

        assert "network_request" in researcher.tool_whitelist
        assert "network_request" not in summarizer.tool_whitelist
        assert "shell_execute" in cli.tool_whitelist

    def test_bulk_sandbox_creation(self, manager):
        """Test creating multiple sandboxes."""
        for i in range(10):
            manager.create_sandbox(f"agent_{i}", role="researcher")

        health = manager.get_system_health()
        assert health["total_agents"] == 10
        assert health["quarantined_agents"] == 0
