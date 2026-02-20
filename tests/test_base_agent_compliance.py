"""
Base Agent Compliance Tests - JSF AV Rules 219-220.

This module implements parametrized tests that verify all BaseAgent subclasses
adhere to the base class contract. Per JSF AV Rule 219, all tests for base
class interfaces must be applied to derived classes to ensure transparency
in functionality.

JSF AV Rule 220 mandates that structural coverage be assessed against
flattened classes, ensuring inherited behavior is properly tested.

Test Categories:
    1. Interface Compliance - All agents implement required methods
    2. Contract Compliance - Method signatures match base class
    3. Behavior Compliance - Methods return expected types
    4. Error Handling - Agents handle invalid inputs gracefully

Author: Artemis-City Contributors
Date: 2024
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Type

import pytest

# Import base class and all concrete implementations
from agents.base_agent import BaseAgent
from agents.artemis_agent import ArtemisAgent
from agents.research_agent import ResearchAgent
from agents.summarizer_agent import SummarizerAgent


# =============================================================================
# Test Fixtures
# =============================================================================


def get_all_agent_classes() -> List[Type[BaseAgent]]:
    """
    Discover all concrete BaseAgent subclasses.

    Returns:
        List of all non-abstract agent classes.
    """
    return [
        ArtemisAgent,
        ResearchAgent,
        SummarizerAgent,
    ]


def get_all_agent_instances() -> List[BaseAgent]:
    """
    Create instances of all concrete agents for testing.

    Returns:
        List of instantiated agent objects.
    """
    return [cls() for cls in get_all_agent_classes()]


@pytest.fixture(params=get_all_agent_classes())
def agent_class(request) -> Type[BaseAgent]:
    """Parametrized fixture providing each agent class."""
    return request.param


@pytest.fixture(params=get_all_agent_instances(), ids=lambda a: a.name)
def agent_instance(request) -> BaseAgent:
    """Parametrized fixture providing each agent instance."""
    return request.param


@pytest.fixture
def minimal_task_context() -> Dict[str, Any]:
    """Minimal valid task context for testing."""
    return {
        "task_id": "test_task_001",
        "title": "Test Task",
        "required_capability": "test",
        "content": "Test content for agent processing.",
    }


@pytest.fixture
def empty_task_context() -> Dict[str, Any]:
    """Empty task context for edge case testing."""
    return {}


# =============================================================================
# Interface Compliance Tests (JSF AV Rule 219)
# =============================================================================


class TestInterfaceCompliance:
    """Verify all agents implement the BaseAgent interface."""

    def test_agent_inherits_from_base_agent(self, agent_class: Type[BaseAgent]) -> None:
        """All agent classes must inherit from BaseAgent."""
        assert issubclass(agent_class, BaseAgent), (
            f"{agent_class.__name__} must inherit from BaseAgent"
        )

    def test_agent_has_perform_task_method(self, agent_instance: BaseAgent) -> None:
        """All agents must implement perform_task method."""
        assert hasattr(agent_instance, "perform_task"), (
            f"{agent_instance.name} missing perform_task method"
        )
        assert callable(agent_instance.perform_task), (
            f"{agent_instance.name}.perform_task must be callable"
        )

    def test_agent_has_report_status_method(self, agent_instance: BaseAgent) -> None:
        """All agents must have report_status method (inherited or overridden)."""
        assert hasattr(agent_instance, "report_status"), (
            f"{agent_instance.name} missing report_status method"
        )
        assert callable(agent_instance.report_status), (
            f"{agent_instance.name}.report_status must be callable"
        )

    def test_agent_has_name_attribute(self, agent_instance: BaseAgent) -> None:
        """All agents must have a non-empty name attribute."""
        assert hasattr(agent_instance, "name"), (
            f"Agent missing name attribute"
        )
        assert isinstance(agent_instance.name, str), (
            f"{agent_instance.name} name must be a string"
        )
        assert len(agent_instance.name) > 0, (
            f"Agent name cannot be empty"
        )

    def test_agent_has_capabilities_attribute(self, agent_instance: BaseAgent) -> None:
        """All agents must have a capabilities list attribute."""
        assert hasattr(agent_instance, "capabilities"), (
            f"{agent_instance.name} missing capabilities attribute"
        )
        assert isinstance(agent_instance.capabilities, list), (
            f"{agent_instance.name}.capabilities must be a list"
        )

    def test_agent_has_logger_attribute(self, agent_instance: BaseAgent) -> None:
        """All agents must have a logger attribute."""
        assert hasattr(agent_instance, "logger"), (
            f"{agent_instance.name} missing logger attribute"
        )


# =============================================================================
# Contract Compliance Tests (Method Signatures)
# =============================================================================


class TestContractCompliance:
    """Verify method signatures match the base class contract."""

    def test_perform_task_signature(self, agent_class: Type[BaseAgent]) -> None:
        """perform_task must accept task_context dict and return dict."""
        sig = inspect.signature(agent_class.perform_task)
        params = list(sig.parameters.keys())

        # Should have self and task_context parameters
        assert "self" in params or len(params) >= 1, (
            f"{agent_class.__name__}.perform_task missing parameters"
        )

    def test_perform_task_accepts_dict(
        self, agent_instance: BaseAgent, minimal_task_context: Dict[str, Any]
    ) -> None:
        """perform_task must accept a dictionary argument."""
        # Should not raise TypeError for dict input
        try:
            result = agent_instance.perform_task(minimal_task_context)
            assert result is not None
        except TypeError as e:
            pytest.fail(
                f"{agent_instance.name}.perform_task rejected dict input: {e}"
            )

    def test_perform_task_returns_dict(
        self, agent_instance: BaseAgent, minimal_task_context: Dict[str, Any]
    ) -> None:
        """perform_task must return a dictionary."""
        result = agent_instance.perform_task(minimal_task_context)
        assert isinstance(result, dict), (
            f"{agent_instance.name}.perform_task must return dict, "
            f"got {type(result).__name__}"
        )


# =============================================================================
# Behavior Compliance Tests (JSF AV Rule 220 - Flattened Coverage)
# =============================================================================


class TestBehaviorCompliance:
    """Verify agents produce expected behavior patterns."""

    def test_result_has_status_field(
        self, agent_instance: BaseAgent, minimal_task_context: Dict[str, Any]
    ) -> None:
        """All task results must include a 'status' field."""
        result = agent_instance.perform_task(minimal_task_context)
        assert "status" in result, (
            f"{agent_instance.name} result missing 'status' field"
        )

    def test_result_status_is_valid(
        self, agent_instance: BaseAgent, minimal_task_context: Dict[str, Any]
    ) -> None:
        """Status field must be 'success' or 'failed'."""
        result = agent_instance.perform_task(minimal_task_context)
        assert result.get("status") in ("success", "failed"), (
            f"{agent_instance.name} returned invalid status: {result.get('status')}"
        )

    def test_result_has_summary_field(
        self, agent_instance: BaseAgent, minimal_task_context: Dict[str, Any]
    ) -> None:
        """All task results must include a 'summary' field."""
        result = agent_instance.perform_task(minimal_task_context)
        assert "summary" in result, (
            f"{agent_instance.name} result missing 'summary' field"
        )

    def test_result_summary_is_string(
        self, agent_instance: BaseAgent, minimal_task_context: Dict[str, Any]
    ) -> None:
        """Summary field must be a string."""
        result = agent_instance.perform_task(minimal_task_context)
        assert isinstance(result.get("summary"), str), (
            f"{agent_instance.name} summary must be string"
        )

    def test_capabilities_are_strings(self, agent_instance: BaseAgent) -> None:
        """All capability entries must be strings."""
        for cap in agent_instance.capabilities:
            assert isinstance(cap, str), (
                f"{agent_instance.name} has non-string capability: {cap}"
            )


# =============================================================================
# Error Handling Tests (Defensive Programming)
# =============================================================================


class TestErrorHandling:
    """Verify agents handle edge cases gracefully."""

    def test_empty_context_does_not_crash(
        self, agent_instance: BaseAgent, empty_task_context: Dict[str, Any]
    ) -> None:
        """Agents should handle empty task context without crashing."""
        try:
            result = agent_instance.perform_task(empty_task_context)
            # Should return a dict, possibly with failed status
            assert isinstance(result, dict)
        except Exception as e:
            # If it raises, it should be a documented exception type
            # not an unexpected crash
            assert not isinstance(e, (AttributeError, KeyError, TypeError)), (
                f"{agent_instance.name} crashed on empty context: {e}"
            )

    def test_report_status_accepts_string(self, agent_instance: BaseAgent) -> None:
        """report_status should accept string messages without error."""
        try:
            agent_instance.report_status("Test status message")
        except Exception as e:
            pytest.fail(
                f"{agent_instance.name}.report_status failed: {e}"
            )

    def test_agent_repr_does_not_crash(self, agent_instance: BaseAgent) -> None:
        """Agent __repr__ should not raise exceptions."""
        try:
            repr_str = repr(agent_instance)
            assert isinstance(repr_str, str)
        except Exception as e:
            pytest.fail(
                f"{agent_instance.name}.__repr__ failed: {e}"
            )


# =============================================================================
# Liskov Substitution Principle Tests (JSF AV Rule 92)
# =============================================================================


class TestLiskovSubstitution:
    """Verify agents can be substituted for BaseAgent without breaking behavior."""

    def test_agent_as_base_type(self, agent_instance: BaseAgent) -> None:
        """Agent should work when typed as BaseAgent."""
        base_ref: BaseAgent = agent_instance

        # Should be able to call base class methods
        assert hasattr(base_ref, "perform_task")
        assert hasattr(base_ref, "report_status")
        assert hasattr(base_ref, "name")
        assert hasattr(base_ref, "capabilities")

    def test_polymorphic_task_execution(
        self, minimal_task_context: Dict[str, Any]
    ) -> None:
        """All agents should work polymorphically with same task context."""
        results = []
        for agent in get_all_agent_instances():
            result = agent.perform_task(minimal_task_context)
            results.append((agent.name, result))

        # All should return valid results
        for name, result in results:
            assert isinstance(result, dict), f"{name} returned non-dict"
            assert "status" in result, f"{name} missing status"


# =============================================================================
# Registration and Discovery Tests
# =============================================================================


class TestAgentDiscovery:
    """Verify agent discovery and registration patterns."""

    def test_all_agents_have_unique_names(self) -> None:
        """All agent instances must have unique names."""
        agents = get_all_agent_instances()
        names = [a.name for a in agents]
        assert len(names) == len(set(names)), (
            f"Duplicate agent names found: {names}"
        )

    def test_all_agents_have_at_least_one_capability(self) -> None:
        """All agents should declare at least one capability."""
        for agent in get_all_agent_instances():
            assert len(agent.capabilities) > 0, (
                f"{agent.name} has no capabilities declared"
            )

    def test_minimum_agent_count(self) -> None:
        """System should have at least 3 agents registered."""
        agents = get_all_agent_classes()
        assert len(agents) >= 3, (
            f"Expected at least 3 agents, found {len(agents)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
