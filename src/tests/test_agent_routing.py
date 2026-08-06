import os
from unittest.mock import Mock, patch

import pytest

import src.mcp.config as config  # Import config to patch OBSIDIAN_VAULT_PATH
import src.mcp.orchestrator as orchestrator_module
from src.agents.base_agent import BaseAgent
from src.integration.agent_registry import AgentRegistry, AgentScore
from src.mcp.orchestrator import Orchestrator


# Fixture for AgentRegistry with isolated DB
@pytest.fixture
def agent_registry(tmp_path):
    """Agent registry.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    db_path = tmp_path / "agent_registry.db"
    return AgentRegistry(db_path=str(db_path))


# Fixture for a mock agent
@pytest.fixture
def mock_agent_a():
    """Mock agent a.

    Returns:
        None: This function does not return a value.
    """
    agent = Mock(spec=BaseAgent)
    agent.name = "Agent A"
    agent.capabilities = ["research", "analysis"]
    agent.perform_task.return_value = {
        "status": "success",
        "summary": "Agent A performed task",
    }
    return agent


@pytest.fixture
def mock_agent_b():
    """Mock agent b.

    Returns:
        None: This function does not return a value.
    """
    agent = Mock(spec=BaseAgent)
    agent.name = "Agent B"
    agent.capabilities = ["summarization"]
    agent.perform_task.return_value = {
        "status": "success",
        "summary": "Agent B performed task",
    }
    return agent


@pytest.fixture
def mock_agent_c():
    """Mock agent c.

    Returns:
        None: This function does not return a value.
    """
    agent = Mock(spec=BaseAgent)
    agent.name = "Agent C"
    agent.capabilities = ["research"]
    agent.perform_task.return_value = {
        "status": "success",
        "summary": "Agent C performed task",
    }
    return agent


class TestAgentRegistry:
    """Provide the TestAgentRegistry abstraction used by this module."""

    def test_initialization(self, agent_registry):
        """Test that initialization.

        Args:
            agent_registry: Agent registry value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert len(agent_registry.agents) == 0
        assert len(agent_registry.scores) == 0

    def test_register_agent(self, agent_registry, mock_agent_a):
        """Test that register agent.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_a: Mock agent a value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_a)
        assert mock_agent_a.name in agent_registry.agents
        assert isinstance(agent_registry.scores[mock_agent_a.name], AgentScore)
        assert agent_registry.scores[mock_agent_a.name].composite_score > 0

    def test_get_agent(self, agent_registry, mock_agent_a):
        """Test that get agent.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_a: Mock agent a value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_a)
        retrieved_agent = agent_registry.get_agent(mock_agent_a.name)
        assert retrieved_agent == mock_agent_a

    def test_route_task_highest_score(self, agent_registry, mock_agent_a, mock_agent_c):
        """Test that route task highest score.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_a: Mock agent a value used by this operation.
            mock_agent_c: Mock agent c value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_a)
        agent_registry.register_agent(mock_agent_c)

        # Manually set scores for predictable routing
        agent_registry.scores[mock_agent_a.name].accuracy = 0.9
        agent_registry.scores[mock_agent_a.name].alignment = 0.8
        agent_registry.scores[mock_agent_a.name].efficiency = 0.7

        agent_registry.scores[mock_agent_c.name].accuracy = 0.6
        agent_registry.scores[mock_agent_c.name].alignment = 0.7
        agent_registry.scores[mock_agent_c.name].efficiency = 0.8

        task = {"required_capability": "research"}
        best_agent_name = agent_registry.route_task(task)
        assert best_agent_name == mock_agent_a.name

    def test_route_task_no_matching_capability(self, agent_registry, mock_agent_b):
        """Test that route task no matching capability.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_b: Mock agent b value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_b)
        task = {"required_capability": "research"}
        with pytest.raises(
            ValueError, match="No agent found with the required capability"
        ):
            agent_registry.route_task(task)

    def test_route_task_empty_registry(self, agent_registry):
        """Test that route task empty registry.

        Args:
            agent_registry: Agent registry value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        task = {"required_capability": "research"}
        with pytest.raises(
            ValueError, match="No agent found with the required capability"
        ):
            agent_registry.route_task(task)

    def test_route_task_missing_capability_in_task(self, agent_registry, mock_agent_a):
        """Test that route task missing capability in task.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_a: Mock agent a value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_a)
        task = {"title": "some task"}
        with pytest.raises(
            ValueError, match="Task dictionary must contain a 'required_capability' key"
        ):
            agent_registry.route_task(task)

    def test_update_score(self, agent_registry, mock_agent_a):
        """Test that update score.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_a: Mock agent a value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_a)
        initial_score = agent_registry.scores[mock_agent_a.name].accuracy
        agent_registry.update_score(mock_agent_a.name, "accuracy", 0.1)
        assert agent_registry.scores[mock_agent_a.name].accuracy == initial_score + 0.1

    def test_update_score_respects_bounds(self, agent_registry, mock_agent_a):
        """Test that update score respects bounds.

        Args:
            agent_registry: Agent registry value used by this operation.
            mock_agent_a: Mock agent a value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        agent_registry.register_agent(mock_agent_a)
        agent_registry.scores[mock_agent_a.name].accuracy = 0.9
        agent_registry.update_score(
            mock_agent_a.name, "accuracy", 0.2
        )  # Should cap at 1.0
        assert agent_registry.scores[mock_agent_a.name].accuracy == 1.0

        agent_registry.scores[mock_agent_a.name].efficiency = 0.1
        agent_registry.update_score(
            mock_agent_a.name, "efficiency", -0.2
        )  # Should cap at 0.0
        assert agent_registry.scores[mock_agent_a.name].efficiency == 0.0

    def test_learning_outcome_updates_registry_hebbian_and_governance_fields(
        self, agent_registry, mock_agent_a
    ):
        """The registry mirrors learning values and computes trust from history."""
        agent_registry.register_agent(mock_agent_a)
        learning = {
            "weight": 1.08,
            "delta": 0.08,
            "activation_count": 1,
            "success_rate": 1.0,
            "task_type": "research",
            "pair_bonus": 0.02,
            "timing_score": 0.5,
            "routing_intelligence": 0.4,
            "oscillation_rate": 0.6,
            "sentinel_alert": True,
            "sentinel_samples": 50,
        }
        agent_registry.record_learning_outcome(
            mock_agent_a.name, success=True, learning=learning
        )
        agent_registry.record_learning_outcome(
            mock_agent_a.name, success=False, learning=learning
        )

        record = agent_registry.store.get_agent_record(mock_agent_a.name)
        assert record["execution_count"] == 2
        assert record["successful_executions"] == 1
        assert record["failed_executions"] == 1
        assert record["trust_score"] == pytest.approx(0.825)
        assert record["hebbian_weight"] == pytest.approx(1.08)
        assert record["hebbian_task_type"] == "research"
        assert record["hebbian_oscillation_rate"] == pytest.approx(0.6)
        assert record["hebbian_sentinel_alert"] is True
        assert record["hebbian_sentinel_samples"] == 50


@pytest.mark.integration
class TestOrchestratorRouting:
    """Provide the TestOrchestratorRouting abstraction used by this module."""

    @pytest.fixture(autouse=True)
    def setup_orchestrator(self, monkeypatch, tmp_path):
        # Create a temporary directory for the mocked Obsidian vault
        """Setup orchestrator.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        self._temp_obsidian_vault = str(tmp_path / "obsidian_vault")
        os.makedirs(self._temp_obsidian_vault, exist_ok=True)
        monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("ARTEMIS_LOG_DIR", str(tmp_path / "logs"))

        # Patch OBSIDIAN_VAULT_PATH to point to the temporary directory
        monkeypatch.setattr(config, "OBSIDIAN_VAULT_PATH", self._temp_obsidian_vault)

        # Mock ObsidianManager methods that interact with the filesystem
        with patch("src.mcp.orchestrator.ObsidianManager") as MockObsidianManager:
            mock_obs_manager_instance = MockObsidianManager.return_value
            mock_obs_manager_instance._get_full_path.return_value = os.path.join(
                self._temp_obsidian_vault, "dummy_path"
            )
            mock_obs_manager_instance.create_folder.return_value = None
            mock_obs_manager_instance.list_notes_in_folder.return_value = []
            mock_obs_manager_instance.read_note.return_value = None
            mock_obs_manager_instance.write_note.return_value = None

            # Mock only vault/vector dependencies. The real learning and
            # registry stores are exercised inside the isolated temp data dir.
            mock_vector_store_instance = Mock()
            mock_vector_store_instance.count.return_value = 0

            with (
                patch("src.mcp.orchestrator.ObsidianParser"),
                patch("src.mcp.orchestrator.ObsidianGenerator"),
                patch("src.mcp.orchestrator.MemoryBus") as MockMemoryBus,
            ):
                mock_memory_bus_instance = MockMemoryBus.return_value
                mock_memory_bus_instance.write_note_with_embedding.return_value = {
                    "status": "success"
                }
                mock_memory_bus_instance.read.return_value = []

                self.orchestrator = Orchestrator(
                    vector_store=mock_vector_store_instance
                )

        yield  # Run the test

        # tmp_path owns cleanup; no live repository database is touched.

    def test_route_and_execute_task_success(self, mock_agent_a):
        # Dynamically create and register a mock agent to override the default Orchestrator agents
        # This is needed because the Orchestrator's __init__ registers its own agent instances
        # We want to use our specific mock_agent_a for testing.
        """Test that route and execute task success.

        Args:
            mock_agent_a: Mock agent a value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        mock_orchestrator_agent_a = Mock(spec=BaseAgent)
        mock_orchestrator_agent_a.name = "Agent A"
        mock_orchestrator_agent_a.capabilities = ["research", "analysis"]
        mock_orchestrator_agent_a.perform_task.return_value = {
            "status": "success",
            "summary": "Agent A performed task",
        }

        # Clear existing agents from the registry and register our mock agent
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.register_agent(mock_orchestrator_agent_a)

        # Set specific scores for routing
        self.orchestrator.agent_registry.scores[
            mock_orchestrator_agent_a.name
        ].accuracy = 0.9
        self.orchestrator.agent_registry.scores[
            mock_orchestrator_agent_a.name
        ].efficiency = 0.9

        task_context = {
            "task_id": "test_routing_task",
            "required_capability": "research",
            "content": "dummy content",
        }

        result = self.orchestrator.route_and_execute_task(task_context)

        assert result["status"] == "success"
        mock_orchestrator_agent_a.perform_task.assert_called_once()
        dispatched_context = mock_orchestrator_agent_a.perform_task.call_args.args[0]
        assert dispatched_context | task_context == dispatched_context
        assert dispatched_context["provenance_id"] == result["provenance_id"]
        record = self.orchestrator.agent_registry.store.get_agent_record("Agent A")
        assert record["execution_count"] == 1
        assert record["hebbian_weight"] is not None
        assert record["trust_score"] == pytest.approx(1.0)

    def test_atp_headers_drive_scoped_routing_and_provenance(self, monkeypatch):
        summarizer = Mock(spec=BaseAgent)
        summarizer.name = "ATP Summarizer"
        summarizer.capabilities = ["text_summarization"]
        summarizer.perform_task.return_value = {
            "status": "success",
            "summary": "condensed",
        }
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.register_agent(summarizer)

        run_logger = Mock()

        def log_event(_event, _component, *_args, **kwargs):
            return kwargs.get("prov_id") or "child-provenance"

        run_logger.log_event.side_effect = log_event
        monkeypatch.setattr(orchestrator_module, "_run_logger", run_logger)

        result = self.orchestrator.route_and_execute_task(
            {
                "task_id": "atp_scoped_route",
                "content": (
                    "#Mode: Synthesize\n"
                    "#Context: Summarize a report\n"
                    "#Priority: High\n"
                    "#ActionType: Summarize\n"
                    "#TargetZone: reports\n\n"
                    "A long report body."
                ),
            }
        )

        assert result["status"] == "success"
        assert result["atp"]["action_type"] == "Summarize"
        dispatched_context = summarizer.perform_task.call_args.args[0]
        assert dispatched_context["content"] == "A long report body."
        assert dispatched_context["required_capability"] == "text_summarization"
        assert dispatched_context["routing_scope"] == "atp:summarize:text_summarization"
        assert dispatched_context["provenance_id"] == result["provenance_id"]
        prompt_call = next(
            call
            for call in run_logger.log_event.call_args_list
            if call.args[0] == "prompt_received"
        )
        assert prompt_call.kwargs["prov_id"] == result["provenance_id"]
        child_calls = [
            call
            for call in run_logger.log_event.call_args_list
            if call.args[0] != "prompt_received"
        ]
        assert child_calls
        assert all(
            call.kwargs["parent_prov_id"] == result["provenance_id"]
            for call in child_calls
        )

    def test_atp_execution_fails_closed_without_provenance_sink(self, monkeypatch):
        monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: None)

        with pytest.raises(RuntimeError, match="provenance sink is unavailable"):
            self.orchestrator.route_and_execute_task(
                {
                    "task_id": "atp_no_provenance",
                    "content": (
                        "#Mode: Build\n"
                        "#Context: Verify fail-closed provenance\n"
                        "#ActionType: Execute\n"
                        "#TargetZone: kernel\n\n"
                        "Run this task."
                    ),
                }
            )

    def test_route_persists_full_routing_decision(self, mock_agent_a, monkeypatch):
        routed_agent = Mock(spec=BaseAgent)
        routed_agent.name = "Agent A"
        routed_agent.capabilities = ["research"]
        routed_agent.perform_task.return_value = {
            "status": "success",
            "summary": "done",
        }
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.register_agent(routed_agent)
        run_logger = Mock()
        monkeypatch.setattr(orchestrator_module, "_run_logger", run_logger)

        result = self.orchestrator.route_and_execute_task(
            {
                "task_id": "route_audit",
                "required_capability": "research",
                "content": "test",
            }
        )

        assert result["status"] == "success"
        routing_calls = [
            call
            for call in run_logger.log_event.call_args_list
            if call.args and call.args[0] == "routing_decision"
        ]
        assert len(routing_calls) == 1
        metadata = routing_calls[0].args[2]
        assert metadata["chosen_agent"] == "Agent A"
        assert metadata["decision"]["candidates"][0]["name"] == "Agent A"

    def test_sandbox_denies_missing_capability_without_hebbian_update(self):
        agent = Mock(spec=BaseAgent)
        agent.name = "Capability Limited Agent"
        agent.capabilities = ["research"]
        agent.perform_task.return_value = {"status": "success", "summary": "wrong"}
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.register_agent(agent)

        result = self.orchestrator.assign_and_execute_task(
            agent.name,
            {
                "task_id": "governance_denial",
                "required_capability": "text_summarization",
            },
        )

        assert result["status"] == "failed"
        assert result["governance"]["violation_type"] == "missing_capability"
        agent.perform_task.assert_not_called()
        state = self.orchestrator.agent_registry.get_governance_state(agent.name)
        assert state["violation_count"] == 1
        assert self.orchestrator.hebbian.get_agent_average_weight(agent.name) == 0.0
        trust_score = self.orchestrator.trust_interface.get_trust_score(agent.name)
        assert trust_score.score == pytest.approx(state["trust_score"])

    def test_route_and_execute_task_no_agent_for_capability(self):
        # Clear existing agents from the registry to ensure no agent matches
        """Test that route and execute task no agent for capability.

        Returns:
            None: This function does not return a value.
        """
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.scores.clear()

        task_context = {
            "task_id": "test_routing_task",
            "required_capability": "non_existent_cap",
        }
        result = self.orchestrator.route_and_execute_task(task_context)
        assert result["status"] == "failed"
        assert "No agent found with the required capability" in result["error"]

    def test_assign_and_execute_task_failed_result_marks_note_failed(self):
        """A normal failed agent result must propagate to the task note."""
        failed_agent = Mock(spec=BaseAgent)
        failed_agent.name = "Failing Agent"
        failed_agent.capabilities = ["research"]
        failed_agent.perform_task.return_value = {
            "status": "failed",
            "summary": "LLM execution unavailable",
            "error": "Exo has no running model",
        }
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.register_agent(failed_agent)
        self.orchestrator.update_task_status_in_obsidian = Mock()

        result = self.orchestrator.assign_and_execute_task(
            failed_agent.name,
            {
                "task_id": "failed_llm_task",
                "required_capability": "research",
                "content": "test",
            },
            "Agent Inputs/failed_llm_task.md",
        )

        assert result["status"] == "failed"
        self.orchestrator.update_task_status_in_obsidian.assert_called_once_with(
            "Agent Inputs/failed_llm_task.md", "failed", "failed_llm_task"
        )

    def test_route_and_execute_task_orchestrator_agents_are_used_by_default(self):
        # This test verifies that the Orchestrator's default agents are registered and can be routed to
        # The Orchestrator's __init__ method will have already registered ArtemisAgent, ResearchAgent, SummarizerAgent

        # Test ResearchAgent
        """Test that route and execute task orchestrator agents are used by default.

        Returns:
            None: This function does not return a value.
        """
        research_task_context = {
            "task_id": "test_research_task",
            "required_capability": "web_search",
            "content": "research topic",
            "disable_llm_delegate": True,
        }
        result = self.orchestrator.route_and_execute_task(research_task_context)
        assert result["status"] == "success"

        # Test SummarizerAgent
        summarize_task_context = {
            "task_id": "test_summarize_task",
            "required_capability": "text_summarization",
            "content": "text to summarize",
            "disable_llm_delegate": True,
        }
        # LLMAgent now legitimately competes in the text_summarization domain.
        # Pin this compliance check to the built-in summarizer so it exercises
        # its explicit offline baseline rather than making a live Exo call.
        result = self.orchestrator.assign_and_execute_task(
            "Summarizer Agent", summarize_task_context
        )
        assert result["status"] == "success"
