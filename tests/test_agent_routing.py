import os
import shutil
import tempfile
from unittest.mock import Mock, patch

import pytest

import importlib
import sys

sys.modules["types"] = importlib.import_module("src.types")

from integration.agent_registry import AgentRegistry, AgentScore
from agents.base_agent import BaseAgent
from mcp.orchestrator import Orchestrator
import mcp.config as config  # Import config to patch OBSIDIAN_VAULT_PATH


# Fixture for AgentRegistry with isolated DB
@pytest.fixture
def agent_registry(tmp_path):
    db_path = tmp_path / "agent_registry.db"
    return AgentRegistry(db_path=str(db_path))


# Fixture for a mock agent
@pytest.fixture
def mock_agent_a():
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
    agent = Mock(spec=BaseAgent)
    agent.name = "Agent C"
    agent.capabilities = ["research"]
    agent.perform_task.return_value = {
        "status": "success",
        "summary": "Agent C performed task",
    }
    return agent


class TestAgentRegistry:
    def test_initialization(self, agent_registry):
        assert len(agent_registry.agents) == 0
        assert len(agent_registry.scores) == 0

    def test_register_agent(self, agent_registry, mock_agent_a):
        agent_registry.register_agent(mock_agent_a)
        assert mock_agent_a.name in agent_registry.agents
        assert isinstance(agent_registry.scores[mock_agent_a.name], AgentScore)
        assert agent_registry.scores[mock_agent_a.name].composite_score > 0

    def test_get_agent(self, agent_registry, mock_agent_a):
        agent_registry.register_agent(mock_agent_a)
        retrieved_agent = agent_registry.get_agent(mock_agent_a.name)
        assert retrieved_agent == mock_agent_a

    def test_route_task_highest_score(self, agent_registry, mock_agent_a, mock_agent_c):
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
        agent_registry.register_agent(mock_agent_b)
        task = {"required_capability": "research"}
        with pytest.raises(
            ValueError, match="No agent found with the required capability"
        ):
            agent_registry.route_task(task)

    def test_route_task_empty_registry(self, agent_registry):
        task = {"required_capability": "research"}
        with pytest.raises(
            ValueError, match="No agent found with the required capability"
        ):
            agent_registry.route_task(task)

    def test_route_task_missing_capability_in_task(self, agent_registry, mock_agent_a):
        agent_registry.register_agent(mock_agent_a)
        task = {"title": "some task"}
        with pytest.raises(
            ValueError, match="Task dictionary must contain a 'required_capability' key"
        ):
            agent_registry.route_task(task)

    def test_update_score(self, agent_registry, mock_agent_a):
        agent_registry.register_agent(mock_agent_a)
        initial_score = agent_registry.scores[mock_agent_a.name].accuracy
        agent_registry.update_score(mock_agent_a.name, "accuracy", 0.1)
        assert agent_registry.scores[mock_agent_a.name].accuracy == initial_score + 0.1

    def test_update_score_respects_bounds(self, agent_registry, mock_agent_a):
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


@pytest.mark.integration
class TestOrchestratorRouting:
    @pytest.fixture(autouse=True)
    def setup_orchestrator(self, monkeypatch):
        # Create a temporary directory for the mocked Obsidian vault
        self._temp_obsidian_vault = tempfile.mkdtemp()

        # Patch OBSIDIAN_VAULT_PATH to point to the temporary directory
        monkeypatch.setattr(config, "OBSIDIAN_VAULT_PATH", self._temp_obsidian_vault)

        # Mock ObsidianManager methods that interact with the filesystem
        with patch("mcp.orchestrator.ObsidianManager") as MockObsidianManager:
            mock_obs_manager_instance = MockObsidianManager.return_value
            mock_obs_manager_instance._get_full_path.return_value = os.path.join(
                self._temp_obsidian_vault, "dummy_path"
            )
            mock_obs_manager_instance.create_folder.return_value = None
            mock_obs_manager_instance.list_notes_in_folder.return_value = []
            mock_obs_manager_instance.read_note.return_value = None
            mock_obs_manager_instance.write_note.return_value = None

            # Mock ObsidianParser, ObsidianGenerator, and HebbianWeightManager
            with patch("mcp.orchestrator.ObsidianParser"), patch(
                "mcp.orchestrator.ObsidianGenerator"
            ), patch("mcp.orchestrator.HebbianWeightManager"), patch(
                "mcp.orchestrator.LocalVectorStore"
            ) as MockVectorStore, patch(
                "mcp.orchestrator.MemoryBus"
            ) as MockMemoryBus:

                mock_vector_store_instance = MockVectorStore.return_value
                mock_vector_store_instance.count.return_value = 0

                mock_memory_bus_instance = MockMemoryBus.return_value
                mock_memory_bus_instance.write_note_with_embedding.return_value = {
                    "status": "success"
                }
                mock_memory_bus_instance.read.return_value = []

                self.orchestrator = Orchestrator()

        yield  # Run the test

        # Clean up the temporary directory after the test
        shutil.rmtree(self._temp_obsidian_vault)

    def test_route_and_execute_task_success(self, mock_agent_a):
        # Dynamically create and register a mock agent to override the default Orchestrator agents
        # This is needed because the Orchestrator's __init__ registers its own agent instances
        # We want to use our specific mock_agent_a for testing.
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
        mock_orchestrator_agent_a.perform_task.assert_called_once_with(task_context)

    def test_route_and_execute_task_no_agent_for_capability(self):
        # Clear existing agents from the registry to ensure no agent matches
        self.orchestrator.agent_registry.agents.clear()
        self.orchestrator.agent_registry.scores.clear()

        task_context = {
            "task_id": "test_routing_task",
            "required_capability": "non_existent_cap",
        }
        result = self.orchestrator.route_and_execute_task(task_context)
        assert result["status"] == "failed"
        assert "No agent found with the required capability" in result["error"]

    def test_route_and_execute_task_orchestrator_agents_are_used_by_default(self):
        # This test verifies that the Orchestrator's default agents are registered and can be routed to
        # The Orchestrator's __init__ method will have already registered ArtemisAgent, ResearchAgent, SummarizerAgent

        # Test ResearchAgent
        research_task_context = {
            "task_id": "test_research_task",
            "required_capability": "web_search",
            "content": "research topic",
        }
        result = self.orchestrator.route_and_execute_task(research_task_context)
        assert result["status"] == "success"

        # Test SummarizerAgent
        summarize_task_context = {
            "task_id": "test_summarize_task",
            "required_capability": "text_summarization",
            "content": "text to summarize",
        }
        result = self.orchestrator.route_and_execute_task(summarize_task_context)
        assert result["status"] == "success"
