"""Tests for the base agent (src/agents/base_agent.py)."""

import pytest
from src.agents.base_agent import BaseAgent


class _ConcreteAgent(BaseAgent):
    """Minimal concrete agent for testing."""

    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "done"}


class TestBaseAgentConstruction:
    """Provide the TestBaseAgentConstruction abstraction used by this module.
    """
    def test_basic(self):
        """Test that basic.
        
        Returns:
            None: This function does not return a value.
        """
        agent = _ConcreteAgent("TestBot", capabilities=["research"])
        assert agent.name == "TestBot"
        assert agent.capabilities == ["research"]

    def test_default_capabilities(self):
        """Test that default capabilities.
        
        Returns:
            None: This function does not return a value.
        """
        agent = _ConcreteAgent("TestBot")
        assert agent.capabilities == []

    def test_empty_name_raises(self):
        """Test that empty name raises.
        
        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(ValueError, match="non-empty"):
            _ConcreteAgent("")

    def test_whitespace_name_raises(self):
        """Test that whitespace name raises.
        
        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(ValueError, match="non-empty"):
            _ConcreteAgent("   ")

    def test_none_name_raises(self):
        """Test that none name raises.
        
        Returns:
            None: This function does not return a value.
        """
        with pytest.raises((ValueError, TypeError)):
            _ConcreteAgent(None)


class TestBaseAgentBehaviour:
    """Provide the TestBaseAgentBehaviour abstraction used by this module.
    """

    @pytest.fixture
    def agent(self):
        """Agent.
        
        Returns:
            None: This function does not return a value.
        """
        return _ConcreteAgent("Bot", capabilities=["code_review"])

    def test_perform_task(self, agent):
        """Test that perform task.
        
        Args:
            agent: Agent instance or agent identifier associated with the operation.
        
        Returns:
            None: This function does not return a value.
        """
        result = agent.perform_task({"task_id": "1"})
        assert result["status"] == "success"

    def test_validate_task_context_dict(self, agent):
        """Test that validate task context dict.
        
        Args:
            agent: Agent instance or agent identifier associated with the operation.
        
        Returns:
            None: This function does not return a value.
        """
        assert agent.validate_task_context({"task_id": "1"}) is True

    def test_validate_task_context_non_dict(self, agent):
        """Test that validate task context non dict.
        
        Args:
            agent: Agent instance or agent identifier associated with the operation.
        
        Returns:
            None: This function does not return a value.
        """
        assert agent.validate_task_context("not a dict") is False
        assert agent.validate_task_context(None) is False

    def test_report_status(self, agent):
        # Should not raise
        """Test that report status.
        
        Args:
            agent: Agent instance or agent identifier associated with the operation.
        
        Returns:
            None: This function does not return a value.
        """
        agent.report_status("working on it")

    def test_logger_property(self, agent):
        """Test that logger property.
        
        Args:
            agent: Agent instance or agent identifier associated with the operation.
        
        Returns:
            None: This function does not return a value.
        """
        assert agent.logger is not None

    def test_repr(self, agent):
        """Test that repr.
        
        Args:
            agent: Agent instance or agent identifier associated with the operation.
        
        Returns:
            None: This function does not return a value.
        """
        r = repr(agent)
        assert "Bot" in r
        assert "code_review" in r
        assert "_ConcreteAgent" in r


class TestBaseAgentAbstract:
    """Provide the TestBaseAgentAbstract abstraction used by this module.
    """
    def test_cannot_instantiate_directly(self):
        """Test that cannot instantiate directly.
        
        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(TypeError):
            BaseAgent("direct")
