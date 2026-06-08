"""Tests for the LLM agent (src/agents/llm_agent.py)."""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.agents.llm_agent import LLMAgent


class TestLLMAgent:
    """Provide the TestLLMAgent abstraction used by this module."""

    def test_perform_task_success(self):
        """The agent should parse a normal chat-completions response."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {
            "id": "resp_1",
            "choices": [{"message": {"content": "hello from exo"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }

        with patch("src.agents.llm_agent.requests.post", return_value=mocked_response):
            result = agent.perform_task({"prompt": "hello"})

        assert result["status"] == "success"
        assert result["summary"] == "hello from exo"
        assert result["provider"] == "exo"
        assert result["model"] == "test-model"

    def test_perform_task_fallback_when_endpoint_unavailable(self):
        """The agent should return a fallback response when Exo calls fail."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")

        with patch(
            "src.agents.llm_agent.requests.post",
            side_effect=RuntimeError("connection failed"),
        ):
            result = agent.perform_task({"prompt": "test prompt"})

        assert result["status"] == "success"
        assert result["provider"] == "fallback"
        assert "Exo is unavailable" in result["summary"]

    def test_perform_task_requires_prompt_or_messages(self):
        """An empty payload should fail fast with a clear message."""
        agent = LLMAgent()
        result = agent.perform_task({})
        assert result["status"] == "failed"
        assert "No prompt or messages provided" in result["summary"]
