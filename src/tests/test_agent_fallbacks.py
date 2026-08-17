"""Regression tests for truthful built-in agent fallback behavior."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.agents.artemis_agent import ArtemisAgent
from src.agents.research_agent import ResearchAgent
from src.agents.summarizer_agent import SummarizerAgent


def _provider_failure() -> dict:
    return {
        "status": "failed",
        "summary": "Exo is still unavailable after retrying.",
        "error": "Exo is still unavailable after retrying.",
        "provider": "exo",
        "fallback_used": False,
        "outcome_class": "provider_failure",
        "learning_eligible": False,
        "failure_kind": "rate_limited",
        "retryable": True,
        "upstream_status_code": 429,
        "attempt_count": 3,
        "retry_after_seconds": 7.0,
        "exo_request": {"request_id": "failed-request", "http_status": 429},
    }


@pytest.mark.parametrize(
    ("agent", "task"),
    [
        (SummarizerAgent(), {"content": "one two three four five"}),
        (ResearchAgent(), {"title": "safe research"}),
        (ArtemisAgent(), {"title": "coordinate", "content": "context"}),
    ],
)
def test_provider_failure_is_never_converted_to_success(
    agent, task, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARTEMIS_SYNTHETIC_AGENT_FALLBACK", raising=False)
    agent.llm_agent.perform_task = Mock(return_value=_provider_failure())

    result = agent.perform_task(task)

    assert result["status"] == "failed"
    assert result["provider"] == "exo"
    assert result["fallback_used"] is False
    assert result["outcome_class"] == "provider_failure"
    assert result["learning_eligible"] is False
    assert result["exo_request"]["request_id"] == "failed-request"
    assert result["retry_after_seconds"] == 7.0
    assert result["delegate_failure"]["upstream_status_code"] == 429


def test_summarizer_passes_shared_source_context_without_mutating_it() -> None:
    llm = Mock()
    llm.perform_task.return_value = {
        "status": "success",
        "summary": "condensed",
        "provider": "exo",
        "model": "model-a",
        "exo_request": {"request_id": "req-a"},
    }
    agent = SummarizerAgent(llm_agent=llm)
    source_context = {
        "task_id": "parent",
        "content": "original requester prompt",
        "memory_context": [{"content": "shared memory"}],
    }
    before = deepcopy(source_context)

    result = agent.perform_task(
        {
            "task_id": "parent:context-compression",
            "content": "full exo output",
            "source_context": source_context,
        }
    )

    assert result["status"] == "success"
    assert result["provider"] == "exo"
    assert result["exo_request"] == {"request_id": "req-a"}
    delegated = llm.perform_task.call_args.args[0]
    assert "full exo output" in delegated["prompt"]
    assert "original requester prompt" in delegated["prompt"]
    assert "shared memory" in delegated["prompt"]
    assert source_context == before


def test_opted_in_summarizer_baseline_is_meaningful_and_non_learning() -> None:
    llm = Mock()
    llm.perform_task.return_value = _provider_failure()
    agent = SummarizerAgent(llm_agent=llm)

    result = agent.perform_task(
        {"content": "short input", "allow_synthetic_fallback": True}
    )

    assert result["status"] == "success"
    assert result["summary"] != "..."
    assert result["provider"] == "extractive_fallback"
    assert result["fallback_used"] is True
    assert result["outcome_class"] == "degraded_success"
    assert result["learning_eligible"] is False
    assert result["degraded"] is True


def test_research_baseline_never_invents_sources() -> None:
    agent = ResearchAgent()

    result = agent.perform_task(
        {
            "title": "topic",
            "keywords": "one,two",
            "disable_llm_delegate": True,
        }
    )

    assert result["status"] == "success"
    assert result["provider"] == "research_planning_fallback"
    assert result["fallback_used"] is True
    assert result["sources_consulted"] == []
    assert result["findings"] == []
    assert result["learning_eligible"] is False
