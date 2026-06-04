"""Tests for the Artemis exception hierarchy (src/exceptions.py)."""

import sys

sys.modules.pop("exceptions", None)
from exceptions import (
    AgentCapabilityError,
    AgentError,
    AgentNotFoundError,
    AgentRegistrationError,
    ArtemisError,
    ConfigurationError,
    GovernanceError,
    GovernanceThresholdError,
    GovernanceViolationError,
    MemoryBusError,
    MemorySystemError,
    ObsidianConnectionError,
    TaskError,
    TaskExecutionError,
    TaskRoutingError,
    TaskValidationError,
    VectorStoreError,
)

import pytest


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
class TestArtemisError:
    """Provide the TestArtemisError abstraction used by this module.
    """
    def test_basic_construction(self):
        """Test that basic construction.
        
        Returns:
            None: This function does not return a value.
        """
        err = ArtemisError("something broke")
        assert str(err) == "something broke"
        assert err.message == "something broke"
        assert err.error_code is None
        assert err.details == {}

    def test_with_error_code(self):
        """Test that with error code.
        
        Returns:
            None: This function does not return a value.
        """
        err = ArtemisError("fail", error_code="E001")
        assert str(err) == "[E001] fail"

    def test_with_details(self):
        """Test that with details.
        
        Returns:
            None: This function does not return a value.
        """
        err = ArtemisError("fail", details={"key": "val"})
        assert err.details == {"key": "val"}

    def test_to_dict_minimal(self):
        """Test that to dict minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = ArtemisError("boom")
        d = err.to_dict()
        assert d["error"] == "ArtemisError"
        assert d["message"] == "boom"
        assert "error_code" not in d
        assert "details" not in d

    def test_to_dict_full(self):
        """Test that to dict full.
        
        Returns:
            None: This function does not return a value.
        """
        err = ArtemisError("boom", error_code="E001", details={"x": 1})
        d = err.to_dict()
        assert d["error_code"] == "E001"
        assert d["details"] == {"x": 1}

    def test_is_exception(self):
        """Test that is exception.
        
        Returns:
            None: This function does not return a value.
        """
        assert issubclass(ArtemisError, Exception)


# ---------------------------------------------------------------------------
# Task exceptions
# ---------------------------------------------------------------------------
class TestTaskExceptions:
    """Provide the TestTaskExceptions abstraction used by this module.
    """
    def test_task_error_inherits(self):
        """Test that task error inherits.
        
        Returns:
            None: This function does not return a value.
        """
        assert issubclass(TaskError, ArtemisError)

    def test_task_routing_error(self):
        """Test that task routing error.
        
        Returns:
            None: This function does not return a value.
        """
        err = TaskRoutingError("no route", task_id="t1", required_capability="research")
        assert err.task_id == "t1"
        assert err.required_capability == "research"
        assert err.error_code == "TASK_ROUTE_001"
        assert err.details["task_id"] == "t1"
        assert err.details["required_capability"] == "research"

    def test_task_routing_error_minimal(self):
        """Test that task routing error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = TaskRoutingError("no route")
        assert err.task_id is None
        assert err.required_capability is None
        assert "task_id" not in err.details

    def test_task_execution_error(self):
        """Test that task execution error.
        
        Returns:
            None: This function does not return a value.
        """
        cause = RuntimeError("disk full")
        err = TaskExecutionError(
            "exec failed", task_id="t2", agent_name="researcher", original_error=cause
        )
        assert err.task_id == "t2"
        assert err.agent_name == "researcher"
        assert err.original_error is cause
        assert err.error_code == "TASK_EXEC_001"
        assert "disk full" in err.details["original_error"]

    def test_task_execution_error_minimal(self):
        """Test that task execution error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = TaskExecutionError("exec failed")
        assert err.task_id is None
        assert err.agent_name is None
        assert err.original_error is None

    def test_task_validation_error(self):
        """Test that task validation error.
        
        Returns:
            None: This function does not return a value.
        """
        err = TaskValidationError(
            "invalid",
            task_id="t3",
            missing_fields=["title"],
            invalid_fields={"priority": "must be int"},
        )
        assert err.task_id == "t3"
        assert err.missing_fields == ["title"]
        assert err.invalid_fields == {"priority": "must be int"}
        assert err.error_code == "TASK_VALID_001"

    def test_task_validation_error_defaults(self):
        """Test that task validation error defaults.
        
        Returns:
            None: This function does not return a value.
        """
        err = TaskValidationError("invalid")
        assert err.missing_fields == []
        assert err.invalid_fields == {}


# ---------------------------------------------------------------------------
# Agent exceptions
# ---------------------------------------------------------------------------
class TestAgentExceptions:
    """Provide the TestAgentExceptions abstraction used by this module.
    """
    def test_agent_error_inherits(self):
        """Test that agent error inherits.
        
        Returns:
            None: This function does not return a value.
        """
        assert issubclass(AgentError, ArtemisError)

    def test_agent_not_found(self):
        """Test that agent not found.
        
        Returns:
            None: This function does not return a value.
        """
        err = AgentNotFoundError("ghost", available_agents=["alice", "bob"])
        assert err.agent_name == "ghost"
        assert err.available_agents == ["alice", "bob"]
        assert "ghost" in str(err)
        assert "alice" in str(err)
        assert err.error_code == "AGENT_NOT_FOUND"

    def test_agent_not_found_minimal(self):
        """Test that agent not found minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = AgentNotFoundError("ghost")
        assert err.available_agents == []
        assert "Available" not in str(err)

    def test_agent_registration_error(self):
        """Test that agent registration error.
        
        Returns:
            None: This function does not return a value.
        """
        err = AgentRegistrationError("dup", "already exists")
        assert err.agent_name == "dup"
        assert err.reason == "already exists"
        assert err.error_code == "AGENT_REG_001"

    def test_agent_capability_error(self):
        """Test that agent capability error.
        
        Returns:
            None: This function does not return a value.
        """
        err = AgentCapabilityError("bob", "fly", agent_capabilities=["walk", "talk"])
        assert err.agent_name == "bob"
        assert err.required_capability == "fly"
        assert err.agent_capabilities == ["walk", "talk"]
        assert err.error_code == "AGENT_CAP_001"

    def test_agent_capability_error_minimal(self):
        """Test that agent capability error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = AgentCapabilityError("bob", "fly")
        assert err.agent_capabilities == []


# ---------------------------------------------------------------------------
# Memory exceptions
# ---------------------------------------------------------------------------
class TestMemoryExceptions:
    """Provide the TestMemoryExceptions abstraction used by this module.
    """
    def test_memory_system_error_inherits(self):
        """Test that memory system error inherits.
        
        Returns:
            None: This function does not return a value.
        """
        assert issubclass(MemorySystemError, ArtemisError)

    def test_memory_bus_error(self):
        """Test that memory bus error.
        
        Returns:
            None: This function does not return a value.
        """
        err = MemoryBusError("sync fail", operation="write", path="/vault/note.md")
        assert err.operation == "write"
        assert err.path == "/vault/note.md"
        assert err.error_code == "MEM_BUS_001"

    def test_memory_bus_error_minimal(self):
        """Test that memory bus error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = MemoryBusError("sync fail")
        assert err.operation is None
        assert err.path is None

    def test_vector_store_error(self):
        """Test that vector store error.
        
        Returns:
            None: This function does not return a value.
        """
        err = VectorStoreError(
            "embed fail", operation="upsert", query="long query " * 20
        )
        assert err.operation == "upsert"
        assert err.query == "long query " * 20
        # Details should truncate query to 100 chars
        assert len(err.details["query"]) <= 100
        assert err.error_code == "VEC_STORE_001"

    def test_vector_store_error_minimal(self):
        """Test that vector store error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = VectorStoreError("embed fail")
        assert err.operation is None
        assert err.query is None

    def test_obsidian_connection_error(self):
        """Test that obsidian connection error.
        
        Returns:
            None: This function does not return a value.
        """
        err = ObsidianConnectionError("/vault", "timeout")
        assert err.vault_path == "/vault"
        assert err.reason == "timeout"
        assert "/vault" in str(err)
        assert "timeout" in str(err)
        assert err.error_code == "OBS_CONN_001"


# ---------------------------------------------------------------------------
# Governance exceptions
# ---------------------------------------------------------------------------
class TestGovernanceExceptions:
    """Provide the TestGovernanceExceptions abstraction used by this module.
    """
    def test_governance_error_inherits(self):
        """Test that governance error inherits.
        
        Returns:
            None: This function does not return a value.
        """
        assert issubclass(GovernanceError, ArtemisError)

    def test_governance_violation_error(self):
        """Test that governance violation error.
        
        Returns:
            None: This function does not return a value.
        """
        err = GovernanceViolationError(
            "policy breach", policy="no-delete", violation_details="tried to delete"
        )
        assert err.policy == "no-delete"
        assert err.violation_details == "tried to delete"
        assert err.error_code == "GOV_VIOL_001"

    def test_governance_violation_error_minimal(self):
        """Test that governance violation error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = GovernanceViolationError("policy breach")
        assert err.policy is None
        assert err.violation_details is None

    def test_governance_threshold_error(self):
        """Test that governance threshold error.
        
        Returns:
            None: This function does not return a value.
        """
        err = GovernanceThresholdError(
            "threshold exceeded",
            threshold_name="failure_streak",
            threshold_value=3,
            actual_value=5,
        )
        assert err.threshold_name == "failure_streak"
        assert err.threshold_value == 3
        assert err.actual_value == 5
        assert err.error_code == "GOV_THRESH_001"


# ---------------------------------------------------------------------------
# Configuration exception
# ---------------------------------------------------------------------------
class TestConfigurationError:
    """Provide the TestConfigurationError abstraction used by this module.
    """
    def test_config_error(self):
        """Test that config error.
        
        Returns:
            None: This function does not return a value.
        """
        err = ConfigurationError(
            "bad config", config_key="db_host", expected_type="str"
        )
        assert err.config_key == "db_host"
        assert err.expected_type == "str"
        assert err.error_code == "CONFIG_001"

    def test_config_error_minimal(self):
        """Test that config error minimal.
        
        Returns:
            None: This function does not return a value.
        """
        err = ConfigurationError("bad config")
        assert err.config_key is None
        assert err.expected_type is None


# ---------------------------------------------------------------------------
# Hierarchy checks
# ---------------------------------------------------------------------------
class TestExceptionHierarchy:
    """Verify inheritance and catchability across the Artemis exception hierarchy."""
    @pytest.mark.parametrize(
        "child,parent",
        [
            (TaskError, ArtemisError),
            (TaskRoutingError, TaskError),
            (TaskExecutionError, TaskError),
            (TaskValidationError, TaskError),
            (AgentError, ArtemisError),
            (AgentNotFoundError, AgentError),
            (AgentRegistrationError, AgentError),
            (AgentCapabilityError, AgentError),
            (MemorySystemError, ArtemisError),
            (MemoryBusError, MemorySystemError),
            (VectorStoreError, MemorySystemError),
            (ObsidianConnectionError, MemorySystemError),
            (GovernanceError, ArtemisError),
            (GovernanceViolationError, GovernanceError),
            (GovernanceThresholdError, GovernanceError),
            (ConfigurationError, ArtemisError),
        ],
    )
    def test_inheritance(self, child, parent):
        """Test that inheritance.
        
        Args:
            child: Child value used by this operation.
            parent: Parent value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        assert issubclass(child, parent)

    def test_catch_all_with_base(self):
        """All domain exceptions should be catchable via ArtemisError.
        
        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(ArtemisError):
            raise TaskRoutingError("oops")

        with pytest.raises(ArtemisError):
            raise AgentNotFoundError("ghost")

        with pytest.raises(ArtemisError):
            raise MemoryBusError("fail")

        with pytest.raises(ArtemisError):
            raise GovernanceViolationError("nope")
