"""Tests for the base agent (src/agents/base_agent.py)."""

import sys

sys.modules.pop("agents.base_agent", None)

import pytest
from agents.base_agent import BaseAgent


class _ConcreteAgent(BaseAgent):
    """Minimal concrete agent for testing."""

    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "done"}


class TestBaseAgentConstruction:
    def test_basic(self):
        agent = _ConcreteAgent("TestBot", capabilities=["research"])
        assert agent.name == "TestBot"
        assert agent.capabilities == ["research"]

    def test_default_capabilities(self):
        agent = _ConcreteAgent("TestBot")
        assert agent.capabilities == []

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _ConcreteAgent("")

    def test_whitespace_name_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _ConcreteAgent("   ")

    def test_none_name_raises(self):
        with pytest.raises((ValueError, TypeError)):
            _ConcreteAgent(None)


class TestBaseAgentBehaviour:
    @pytest.fixture
    def agent(self):
        return _ConcreteAgent("Bot", capabilities=["code_review"])

    def test_perform_task(self, agent):
        result = agent.perform_task({"task_id": "1"})
        assert result["status"] == "success"

    def test_validate_task_context_dict(self, agent):
        assert agent.validate_task_context({"task_id": "1"}) is True

    def test_validate_task_context_non_dict(self, agent):
        assert agent.validate_task_context("not a dict") is False
        assert agent.validate_task_context(None) is False

    def test_report_status(self, agent):
        # Should not raise
        agent.report_status("working on it")

    def test_logger_property(self, agent):
        assert agent.logger is not None

    def test_repr(self, agent):
        r = repr(agent)
        assert "Bot" in r
        assert "code_review" in r
        assert "_ConcreteAgent" in r


class TestBaseAgentAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAgent("direct")
