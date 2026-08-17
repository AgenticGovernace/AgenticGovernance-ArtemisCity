"""Focused lifecycle coverage for the production orchestrator.

These tests intentionally construct the orchestrator around lightweight fakes.
That keeps vault, network, and persistent governance stores out of the test run
while exercising the real routing, streaming, memory, and task-note control flow.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import src.mcp.orchestrator as orchestrator_module
from src.mcp.orchestrator import Orchestrator


class _Decision:
    def __init__(self, agent_name: str = "Stream Agent") -> None:
        self.agent_name = agent_name

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "capability": "research",
            "candidates": [{"name": self.agent_name, "blended_score": 0.91}],
        }


def _sandbox_result(
    allowed: bool = True,
    *,
    reason: str | None = None,
    violation_type: str | None = None,
):
    return SimpleNamespace(
        allowed=allowed,
        reason=reason,
        violation_type=violation_type,
    )


@pytest.fixture
def orchestrator(monkeypatch):
    """Build an isolated orchestrator without running its persistent boot flow."""
    instance = Orchestrator.__new__(Orchestrator)
    instance.obs_manager = Mock()
    instance.obs_parser = Mock()
    instance.obs_generator = Mock()
    instance.obs_generator.generate_agent_report.return_value = "# Agent report"
    instance.obs_generator.generate_task_note.return_value = "# Task note"
    instance.memory_bus = Mock()
    instance.memory_bus.sql_store = None
    instance.agent_registry = Mock()
    instance.hebbian = Mock()
    instance.learning_governance = Mock()
    instance.hebbian_router = SimpleNamespace(
        fallback_capability="llm_chat",
        route=Mock(),
    )
    instance.hebbian_routing_enabled = True
    # These cases pin orchestrator behavior *around* routing, so they drive the
    # legacy compatibility path directly via ``hebbian_router.route``. Kernel
    # authorization and eligibility are covered in test_routing_kernel.py.
    instance.routing_kernel = None
    instance.routing_kernel_enabled = False

    # ATP parsing is independently covered; retain a fresh dict so provenance
    # mutations behave exactly like the production entry point.
    instance.prepare_task_context = Mock(side_effect=lambda task: dict(task))
    instance._check_dispatch = Mock(return_value=_sandbox_result())
    instance._enrich_task_with_memory = Mock(side_effect=lambda task: dict(task))
    instance._log_provenance_action = Mock()
    instance._update_hebbian_weights = Mock(
        return_value={
            "task_type": "research",
            "delta": 0.2,
            "weight": 1.2,
            "sentinel_alert": False,
        }
    )

    monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: None)
    return instance


def test_streaming_route_executes_persists_learns_and_completes(orchestrator):
    """A streaming agent leaves the same governed trail as JSON execution."""
    decision = _Decision()
    orchestrator.hebbian_router.route.return_value = decision

    agent = SimpleNamespace(
        name="Stream Agent",
        capabilities=["research"],
        supports_streaming=True,
        stream_task=lambda _context: iter(
            [
                {"type": "token", "text": "one "},
                {"type": "token", "text": "two"},
                {
                    "type": "final",
                    "result": {
                        "status": "success",
                        "summary": "one two",
                        "confidence": 0.9,
                    },
                },
            ]
        ),
    )
    orchestrator.agent_registry.get_agent.return_value = agent
    orchestrator.update_task_status_in_obsidian = Mock()

    events = list(
        orchestrator.stream_route_and_execute(
            {
                "task_id": "stream-1",
                "required_capability": "research",
                "content": "Find evidence",
            },
            "Agent Inputs/stream-1.md",
        )
    )

    assert [event["type"] for event in events] == [
        "routing",
        "token",
        "token",
        "complete",
    ]
    assert events[0]["decision"] == decision.to_dict()
    assert events[-1]["status"] == "success"
    assert events[-1]["summary"] == "one two"
    assert events[-1]["agent_name"] == "Stream Agent"
    assert events[-1]["provenance_id"]
    orchestrator.memory_bus.write_note_with_embedding.assert_called_once()
    report_path, report = (
        orchestrator.memory_bus.write_note_with_embedding.call_args.args
    )
    assert report_path == "Agent Outputs/Stream_Agent_Report_stream-1_5.md"
    assert report == "# Agent report"
    assert (
        orchestrator.memory_bus.write_note_with_embedding.call_args.kwargs["metadata"][
            "provenance_id"
        ]
        == events[-1]["provenance_id"]
    )
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/stream-1.md", "completed", "stream-1"
    )
    assert orchestrator._update_hebbian_weights.call_args.args[:3] == (
        "Stream Agent",
        "stream-1",
        True,
    )
    assert {
        provenance_call.args[1]
        for provenance_call in orchestrator._log_provenance_action.call_args_list
    } >= {"task_start", "memory_persisted", "learning_updated", "task_completed"}


def test_streaming_pinned_nonstream_agent_surfaces_learning_failure(orchestrator):
    """Pinned synchronous agents stream one token and report a lost learning write."""
    agent = SimpleNamespace(
        name="Pinned Agent",
        capabilities=["research"],
        supports_streaming=False,
        perform_task=Mock(return_value={"status": "success", "summary": "finished"}),
    )
    orchestrator.agent_registry.get_agent.return_value = agent
    orchestrator.memory_bus.write_note_with_embedding.side_effect = OSError(
        "vector store offline"
    )
    orchestrator._update_hebbian_weights.side_effect = OSError("hebbian offline")
    orchestrator.update_task_status_in_obsidian = Mock()
    orchestrator.log_routing_decision = Mock()

    events = list(
        orchestrator.stream_route_and_execute(
            {
                "task_id": "pinned-1",
                "agent": "Pinned Agent",
                "required_capability": "research",
            },
            "Agent Inputs/pinned-1.md",
        )
    )

    assert events[0] == {
        "type": "routing",
        "decision": None,
        "agent_name": "Pinned Agent",
    }
    assert events[1] == {"type": "token", "text": "finished"}
    assert events[-1]["status"] == "success"
    assert events[-1]["error"] == "Hebbian persistence failed; see server logs."
    orchestrator.hebbian_router.route.assert_not_called()
    orchestrator.log_routing_decision.assert_called_once()
    assert orchestrator.log_routing_decision.call_args.kwargs["pinned"] is True
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/pinned-1.md", "completed", "pinned-1"
    )


def test_streaming_agent_without_final_event_becomes_failed_result(orchestrator):
    agent = SimpleNamespace(
        name="Incomplete Stream",
        capabilities=["research"],
        supports_streaming=True,
        stream_task=lambda _context: iter([{"type": "token", "text": "partial"}]),
    )
    orchestrator.hebbian_router.route.return_value = _Decision("Incomplete Stream")
    orchestrator.agent_registry.get_agent.return_value = agent

    events = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "unfinished", "required_capability": "research"}
        )
    )

    assert events[-1]["type"] == "complete"
    assert events[-1]["status"] == "failed"
    assert events[-1]["summary"] == "Streaming agent did not emit a final event."
    assert orchestrator._update_hebbian_weights.call_args.args[:3] == (
        "Incomplete Stream",
        "unfinished",
        False,
    )


def test_streaming_execution_exception_is_sanitized_and_learned(orchestrator):
    agent = SimpleNamespace(
        name="Broken Agent",
        capabilities=["research"],
        supports_streaming=False,
        perform_task=Mock(side_effect=RuntimeError("private failure detail")),
    )
    orchestrator.hebbian_router.route.return_value = _Decision("Broken Agent")
    orchestrator.agent_registry.get_agent.return_value = agent
    orchestrator.update_task_status_in_obsidian = Mock()

    events = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "broken", "required_capability": "research"},
            "Agent Inputs/broken.md",
        )
    )

    assert events[-1]["status"] == "failed"
    assert "private failure detail" not in events[-1]["summary"]
    assert events[-1]["error"] == "Task execution failed; see server logs for details."
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/broken.md", "failed", "broken"
    )
    assert orchestrator._update_hebbian_weights.call_args.args[:3] == (
        "Broken Agent",
        "broken",
        False,
    )


def test_streaming_routing_and_governance_error_branches(orchestrator):
    """Routing failures, missing agents, and sandbox denials stop before execution."""
    missing_capability = list(orchestrator.stream_route_and_execute({"task_id": "x"}))
    assert missing_capability == [
        {
            "type": "error",
            "error": "Task dictionary must contain a 'required_capability' or provide a known agent.",
        }
    ]

    orchestrator.hebbian_router.route.side_effect = ValueError("no route")
    orchestrator.update_task_status_in_obsidian = Mock(side_effect=OSError("vault"))
    routing_failure = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "route-fail", "required_capability": "research"},
            "Agent Inputs/route-fail.md",
        )
    )
    assert routing_failure == [
        {"type": "error", "error": "Routing failed; see server logs for details."}
    ]
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/route-fail.md", "routing_failed", "route-fail"
    )

    orchestrator.hebbian_router.route.side_effect = None
    orchestrator.hebbian_router.route.return_value = _Decision("Ghost Agent")
    orchestrator.agent_registry.get_agent.return_value = None
    missing_agent = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "ghost", "required_capability": "research"}
        )
    )
    assert missing_agent[-1] == {
        "type": "error",
        "error": "Agent 'Ghost Agent' not registered with the orchestrator.",
    }

    denied_agent = SimpleNamespace(name="Denied Agent", capabilities=["research"])
    orchestrator.hebbian_router.route.return_value = _Decision("Denied Agent")
    orchestrator.agent_registry.get_agent.return_value = denied_agent
    orchestrator._check_dispatch.return_value = _sandbox_result(
        False,
        reason="policy denied",
        violation_type="missing_capability",
    )
    orchestrator.update_task_status_in_obsidian = Mock()
    denied = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "denied", "required_capability": "research"},
            "Agent Inputs/denied.md",
        )
    )
    assert denied[-1] == {
        "type": "error",
        "error": "Task denied by governance policy; see server logs.",
    }
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/denied.md", "failed", "denied"
    )
    denied_log = next(
        item
        for item in orchestrator._log_provenance_action.call_args_list
        if item.args[1] == "dispatch_denied"
    )
    assert denied_log.args[3]["violation_type"] == "missing_capability"


def test_non_hebbian_route_uses_registry_and_inferred_agent_capability(orchestrator):
    """The configured composite-only fallback still dispatches a known agent."""
    agent = SimpleNamespace(name="Known Agent", capabilities=["research"])
    orchestrator.agent_registry.get_agent.return_value = agent
    orchestrator.agent_registry.route_task.return_value = "Known Agent"
    orchestrator.hebbian_routing_enabled = False
    orchestrator.log_routing_decision = Mock()
    orchestrator.assign_and_execute_task = Mock(
        return_value={"status": "success", "summary": "done"}
    )

    result = orchestrator.route_and_execute_task(
        {"task_id": "registry-route", "agent": "Known Agent"}
    )

    assert result["status"] == "success"
    dispatched = orchestrator.assign_and_execute_task.call_args.args[1]
    assert dispatched["required_capability"] == "research"
    orchestrator.agent_registry.route_task.assert_called_once_with(dispatched)
    orchestrator.log_routing_decision.assert_called_once()
    assert orchestrator.log_routing_decision.call_args.kwargs["decision"] is None


def test_stream_infers_pinned_capability_and_registry_only_route(orchestrator):
    inferred_agent = SimpleNamespace(
        name="Inferred Agent",
        capabilities=["research"],
        supports_streaming=False,
        perform_task=Mock(return_value={"status": "success", "summary": "inferred"}),
    )
    orchestrator.agent_registry.get_agent.return_value = inferred_agent

    inferred_events = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "inferred-stream", "agent": "Inferred Agent"}
        )
    )

    assert inferred_events[0]["agent_name"] == "Inferred Agent"
    dispatched = inferred_agent.perform_task.call_args.args[0]
    assert dispatched["required_capability"] == "research"

    registry_agent = SimpleNamespace(
        name="Registry Agent",
        capabilities=["research"],
        supports_streaming=False,
        perform_task=Mock(return_value={"status": "success", "summary": "registry"}),
    )
    orchestrator.agent_registry.get_agent.return_value = registry_agent
    orchestrator.agent_registry.route_task.return_value = "Registry Agent"
    orchestrator.hebbian_routing_enabled = False

    registry_events = list(
        orchestrator.stream_route_and_execute(
            {"task_id": "registry-stream", "required_capability": "research"}
        )
    )

    assert registry_events[0] == {
        "type": "routing",
        "decision": None,
        "agent_name": "Registry Agent",
    }
    orchestrator.agent_registry.route_task.assert_called_once()


def test_route_failure_marks_original_note(orchestrator):
    orchestrator.hebbian_router.route.side_effect = KeyError("missing route")
    orchestrator.update_task_status_in_obsidian = Mock()

    result = orchestrator.route_and_execute_task(
        {"task_id": "route-error", "required_capability": "research"},
        "Agent Inputs/route-error.md",
    )

    assert result["status"] == "failed"
    assert "missing route" in result["error"]
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/route-error.md", "routing_failed", "route-error"
    )

    orchestrator.hebbian_router.route.side_effect = None
    result = orchestrator.route_and_execute_task(
        {"task_id": "missing-capability"}, "Agent Inputs/missing-capability.md"
    )
    assert result["status"] == "failed"
    assert "required_capability" in result["error"]


def test_assign_execution_error_and_persistence_fallbacks(orchestrator):
    """Direct dispatch handles missing agents, denial, crash, and memory loss."""
    orchestrator.agent_registry.get_agent.return_value = None
    with pytest.raises(ValueError, match="Missing Agent.*not registered"):
        orchestrator.assign_and_execute_task(
            "Missing Agent", {"task_id": "missing", "required_capability": "research"}
        )

    agent = SimpleNamespace(
        name="Direct Agent",
        capabilities=["research"],
        perform_task=Mock(return_value={"status": "success", "summary": "done"}),
    )
    orchestrator.agent_registry.get_agent.return_value = agent
    orchestrator._check_dispatch.return_value = _sandbox_result(
        False, reason=None, violation_type="quarantined"
    )
    orchestrator.update_task_status_in_obsidian = Mock()
    denied = orchestrator.assign_and_execute_task(
        "Direct Agent",
        {"task_id": "denied-direct", "required_capability": "research"},
        "Agent Inputs/denied-direct.md",
    )
    assert denied["error"] == "sandbox denied dispatch"
    orchestrator.update_task_status_in_obsidian.assert_called_with(
        "Agent Inputs/denied-direct.md", "failed", "denied-direct"
    )

    orchestrator._check_dispatch.return_value = _sandbox_result()
    agent.perform_task.side_effect = RuntimeError("agent crashed")
    crashed = orchestrator.assign_and_execute_task(
        "Direct Agent",
        {"task_id": "crashed-direct", "required_capability": "research"},
        "Agent Inputs/crashed-direct.md",
    )
    assert crashed["status"] == "failed"
    assert crashed["summary"] == "Task failed: agent crashed"
    orchestrator.update_task_status_in_obsidian.assert_called_with(
        "Agent Inputs/crashed-direct.md", "failed", "crashed-direct"
    )

    agent.perform_task.side_effect = None
    agent.perform_task.return_value = {"status": "success", "summary": "done"}
    orchestrator.memory_bus.write_note_with_embedding.side_effect = OSError(
        "memory offline"
    )
    persisted = orchestrator.assign_and_execute_task(
        "Direct Agent",
        {"task_id": "memory-direct", "required_capability": "research"},
    )
    assert persisted["status"] == "success"
    assert persisted["provenance_id"]


@pytest.mark.parametrize(
    ("result", "task_success", "expected_outcome"),
    [
        (
            {
                "status": "failed",
                "outcome_class": "provider_failure",
                "learning_eligible": False,
            },
            False,
            "provider_failure",
        ),
        ({"status": "failed", "outcome_class": "cancelled"}, False, "cancelled"),
        (
            {"status": "success", "outcome_class": "degraded_success"},
            True,
            "degraded_success",
        ),
        (
            {
                "status": "success",
                "outcome_class": "success",
                "learning_eligible": False,
            },
            True,
            "success",
        ),
    ],
)
def test_non_agent_outcomes_skip_learning_and_record_provenance(
    orchestrator, result, task_success, expected_outcome
):
    learning = orchestrator._record_execution_learning(
        "LLM Agent",
        "skip-learning",
        {"required_capability": "llm_chat", "provenance_id": "parent"},
        result,
        task_success=task_success,
        duration_ms=7.5,
    )

    assert learning is None
    orchestrator._update_hebbian_weights.assert_not_called()
    skipped = orchestrator._log_provenance_action.call_args
    assert skipped.args[1:3] == ("learning_skipped", "hebbian_weights")
    assert skipped.args[3]["outcome_class"] == expected_outcome


@pytest.mark.parametrize(
    ("outcome_class", "task_success", "learning_success"),
    [("success", True, True), ("agent_failure", False, False)],
)
def test_measured_agent_outcomes_update_learning_with_correct_sign(
    orchestrator, outcome_class, task_success, learning_success
):
    orchestrator._record_execution_learning(
        "Measured Agent",
        "measured-task",
        {"routing_scope": "research", "provenance_id": "parent"},
        {
            "status": "success" if task_success else "failed",
            "outcome_class": outcome_class,
        },
        task_success=task_success,
        duration_ms=4.0,
    )

    assert orchestrator._update_hebbian_weights.call_args.args[:3] == (
        "Measured Agent",
        "measured-task",
        learning_success,
    )


def test_long_exo_output_uses_governed_child_and_shared_source_context(
    orchestrator,
):
    raw_output = "exo-output-" * 8
    retrievals = [{"path": "Agent Outputs/source.md", "score": 0.91}]
    orchestrator.exo_summary_threshold_chars = 20
    orchestrator._enrich_task_with_memory = (
        Orchestrator._enrich_task_with_memory.__get__(orchestrator, Orchestrator)
    )
    orchestrator.memory_bus.read.return_value = retrievals
    orchestrator.hebbian_router.route.return_value = _Decision("Summarizer Agent")

    primary = SimpleNamespace(
        name="LLM Agent",
        capabilities=["llm_chat"],
        perform_task=Mock(
            return_value={
                "status": "success",
                "summary": raw_output,
                "raw_output": raw_output,
                "provider": "exo",
                "model": "exo/model",
                "exo_request": {"request_id": "exo-1", "attempt_count": 1},
            }
        ),
    )
    summarizer = SimpleNamespace(
        name="Summarizer Agent",
        capabilities=["text_summarization"],
        perform_task=Mock(
            return_value={"status": "success", "summary": "bounded context"}
        ),
    )
    orchestrator.agent_registry.get_agent.side_effect = lambda name: {
        "LLM Agent": primary,
        "Summarizer Agent": summarizer,
    }.get(name)

    result = orchestrator.assign_and_execute_task(
        "LLM Agent",
        {
            "task_id": "long-exo",
            "required_capability": "llm_chat",
            "content": "Use contextual evidence",
        },
    )

    assert result["summary"] == "bounded context"
    assert result["compressed_context"] == "bounded context"
    assert "raw_output" not in result
    assert result["provider"] == "exo"
    assert result["model"] == "exo/model"
    assert result["exo_request"]["request_id"] == "exo-1"
    compression = result["output_compression"]
    assert compression["status"] == "compressed"
    assert compression["raw_length"] == len(raw_output)
    assert (
        compression["raw_sha256"]
        == hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
    )
    assert compression["raw_artifact_persisted"] is True
    assert compression["report_persisted"] is True
    assert compression["raw_output_returned"] is False
    assert compression["summarizer_agent"] == "Summarizer Agent"
    assert compression["routing"]["agent_name"] == "Summarizer Agent"

    primary_context = primary.perform_task.call_args.args[0]
    child_context = summarizer.perform_task.call_args.args[0]
    assert primary_context["memory_context"] == retrievals
    assert child_context["source_context"] == primary_context["source_context"]
    assert child_context["source_context"] is not primary_context["source_context"]
    assert child_context["provenance_id"] == primary_context["provenance_id"]
    assert child_context["required_capability"] == "text_summarization"
    assert (
        child_context["routing_scope"] == orchestrator_module.CONTEXT_COMPRESSION_SCOPE
    )
    assert child_context["_skip_memory_enrichment"] is True
    assert child_context["_skip_output_compression"] is True
    assert "Highlight the most important points" in child_context["system_prompt"]
    orchestrator.memory_bus.read.assert_called_once_with(
        "Use contextual evidence", max_results=3
    )

    raw_write = next(
        item
        for item in orchestrator.memory_bus.write_note_with_embedding.call_args_list
        if item.kwargs.get("embed") is False
    )
    assert raw_write.args[1] == raw_output
    assert raw_write.kwargs["metadata"]["content_length"] == len(raw_output)
    assert raw_write.kwargs["metadata"]["content_sha256"] == compression["raw_sha256"]
    parent_report_result = (
        orchestrator.obs_generator.generate_agent_report.call_args.args[2]
    )
    assert "raw_output" not in parent_report_result

    learning_calls = orchestrator._update_hebbian_weights.call_args_list
    assert learning_calls[0].args[:3] == ("LLM Agent", "long-exo", True)
    assert learning_calls[1].args[:3] == (
        "Summarizer Agent",
        "long-exo:context-compression",
        True,
    )
    assert (
        learning_calls[1].kwargs["task_type"]
        == orchestrator_module.CONTEXT_COMPRESSION_SCOPE
    )


def test_failed_long_output_compression_keeps_bounded_audit_metadata(orchestrator):
    raw_output = "long-output" * 5
    orchestrator.exo_summary_threshold_chars = 10
    orchestrator.hebbian_router.route.return_value = _Decision("Summarizer Agent")
    orchestrator.assign_and_execute_task = Mock(
        return_value={"status": "failed", "summary": "summarizer failed"}
    )
    execution_context = {
        "source_context": {"task_id": "parent", "memory_context": ["same"]}
    }

    result = orchestrator._compress_long_exo_output(
        {"task_id": "parent", "provenance_id": "prov"},
        execution_context,
        {
            "status": "success",
            "summary": raw_output,
            "raw_output": raw_output,
            "provider": "exo",
        },
    )

    assert result["summary"].startswith("Long Exo output was preserved")
    assert result["compressed_context"] == result["summary"]
    assert result["output_compression"]["status"] == "failed"
    assert result["output_compression"]["raw_artifact_persisted"] is True
    assert result["raw_output"] == raw_output
    child = orchestrator.assign_and_execute_task.call_args.args[1]
    assert child["source_context"] == execution_context["source_context"]
    assert child["source_context"] is not execution_context["source_context"]


def test_raw_output_is_returned_when_no_durable_copy_exists() -> None:
    result = {
        "raw_output": "only surviving copy",
        "output_compression": {"raw_artifact_persisted": False},
    }

    Orchestrator._remove_preserved_raw_output(result, report_persisted=False)

    assert result["raw_output"] == "only surviving copy"
    assert result["output_compression"]["report_persisted"] is False
    assert result["output_compression"]["raw_output_returned"] is True


def test_zero_threshold_disables_long_output_compression(orchestrator):
    orchestrator.exo_summary_threshold_chars = 0
    result = {
        "status": "success",
        "summary": "unchanged",
        "raw_output": "long raw output",
        "provider": "exo",
    }

    processed = orchestrator._compress_long_exo_output(
        {"task_id": "disabled"}, {"source_context": {}}, result
    )

    assert processed is result
    orchestrator.memory_bus.write_note_with_embedding.assert_not_called()
    orchestrator.hebbian_router.route.assert_not_called()


def test_stream_terminal_event_compresses_but_tokens_remain_raw(
    orchestrator, monkeypatch
):
    raw_output = "raw token stream from exo"
    exo_request = {"request_id": "stream-request", "attempt_count": 1}
    run_logger = Mock()
    run_logger.log_event.return_value = "stream-provenance"
    monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: run_logger)
    orchestrator.exo_summary_threshold_chars = 8
    orchestrator.hebbian_router.route.return_value = _Decision("LLM Agent")
    orchestrator.assign_and_execute_task = Mock(
        return_value={"status": "success", "summary": "compressed terminal"}
    )
    agent = SimpleNamespace(
        name="LLM Agent",
        capabilities=["llm_chat"],
        supports_streaming=True,
        stream_task=lambda _context: iter(
            [
                {"type": "token", "text": "raw token "},
                {"type": "token", "text": "stream from exo"},
                {
                    "type": "final",
                    "result": {
                        "status": "success",
                        "summary": raw_output,
                        "raw_output": raw_output,
                        "provider": "exo",
                        "fallback_used": False,
                        "model": "exo/stream-model",
                        "exo_request": exo_request,
                    },
                },
            ]
        ),
    )
    orchestrator.agent_registry.get_agent.return_value = agent

    events = list(
        orchestrator.stream_route_and_execute(
            {
                "task_id": "long-stream",
                "required_capability": "llm_chat",
                "provenance_id": "stream-provenance",
            }
        )
    )

    assert [event["text"] for event in events if event["type"] == "token"] == [
        "raw token ",
        "stream from exo",
    ]
    terminal = events[-1]
    assert terminal["type"] == "complete"
    assert terminal["summary"] == "compressed terminal"
    assert terminal["provider"] == "exo"
    assert terminal["fallback_used"] is False
    assert terminal["model"] == "exo/stream-model"
    assert terminal["exo_request"] == exo_request
    assert terminal["output_compression"]["status"] == "compressed"
    run_execution = run_logger.log_task_execution.call_args
    assert run_execution.kwargs["metadata"]["provider"] == "exo"
    assert run_execution.kwargs["metadata"]["exo_request"] == exo_request
    assert (
        run_execution.kwargs["metadata"]["output_compression"]["status"] == "compressed"
    )


def test_pending_task_discovery_filters_and_infers_capability(orchestrator):
    orchestrator.obs_manager.list_notes_in_folder.return_value = [
        "pending.md",
        "done.md",
        "invalid.md",
        "empty.md",
    ]
    contents = {
        "Agent Inputs/pending.md": "pending-content",
        "Agent Inputs/done.md": "done-content",
        "Agent Inputs/invalid.md": "invalid-content",
        "Agent Inputs/empty.md": "",
    }
    orchestrator.obs_manager.read_note.side_effect = contents.get
    parsed = {
        "pending-content": {
            "title": "Pending",
            "agent": "Research Agent",
        },
        "done-content": {"title": "Done", "status": "completed"},
        "invalid-content": None,
    }
    orchestrator.obs_parser.parse_task_note.side_effect = parsed.get
    orchestrator.agent_registry.get_agent.side_effect = lambda name: (
        SimpleNamespace(capabilities=["research"]) if name == "Research Agent" else None
    )

    tasks = orchestrator.check_for_new_tasks_from_obsidian()

    assert len(tasks) == 1
    path, task = tasks[0]
    assert path == "Agent Inputs/pending.md"
    assert (
        task["task_id"]
        == "task_" + hashlib.sha256(b"Agent Inputs/pending.md").hexdigest()[:12]
    )
    assert task["required_capability"] == "research"
    assert orchestrator.obs_parser.parse_task_note.call_count == 3


def test_sql_pending_task_discovery_uses_canonical_heads_not_vault(orchestrator):
    """A stale Obsidian projection cannot make a completed SQL task pending again."""
    orchestrator.memory_bus.sql_store = object()
    orchestrator.memory_bus.list_current.return_value = [
        {
            "relative_path": "Agent Inputs/current.md",
            "content": "canonical-completed",
        },
        {
            "relative_path": "Agent Inputs/pending.md",
            "content": "canonical-pending",
        },
        {
            "relative_path": "Agent Inputs/archive/nested.md",
            "content": "nested-pending",
        },
    ]
    orchestrator.obs_parser.parse_task_note.side_effect = lambda content: {
        "canonical-completed": {"title": "Done", "status": "completed"},
        "canonical-pending": {
            "title": "Pending",
            "status": "pending",
            "required_capability": "research",
        },
        "nested-pending": {
            "title": "Nested",
            "status": "pending",
            "required_capability": "research",
        },
    }[content]
    orchestrator.obs_manager.list_notes_in_folder.side_effect = AssertionError(
        "SQL task discovery must not enumerate a derived vault projection"
    )

    tasks = orchestrator.check_for_new_tasks_from_obsidian()

    assert [path for path, _task in tasks] == ["Agent Inputs/pending.md"]
    orchestrator.memory_bus.list_current.assert_called_once_with(
        orchestrator_module.AGENT_INPUT_DIR
    )
    orchestrator.obs_manager.list_notes_in_folder.assert_not_called()
    orchestrator.obs_manager.read_note.assert_not_called()


def test_status_update_writes_through_memory_with_filesystem_fallback(orchestrator):
    orchestrator.memory_bus.read_exact.return_value = {"content": "status: pending"}
    orchestrator.obs_parser.update_status_in_note.return_value = "status: completed"

    orchestrator.update_task_status_in_obsidian(
        "Agent Inputs/task.md", "completed", "task-1"
    )
    orchestrator.memory_bus.write_note_with_embedding.assert_called_once_with(
        "Agent Inputs/task.md",
        "status: completed",
        metadata={"task_id": "task-1", "status": "completed"},
        provenance_id=None,
        source_agent="Artemis Orchestrator",
    )
    orchestrator.obs_manager.write_note.assert_not_called()

    orchestrator.memory_bus.write_note_with_embedding.reset_mock()
    orchestrator.memory_bus.write_note_with_embedding.side_effect = OSError(
        "embedding unavailable"
    )
    orchestrator.update_task_status_in_obsidian(
        "Agent Inputs/task.md", "failed", "task-1"
    )
    orchestrator.obs_manager.write_note.assert_called_once_with(
        "Agent Inputs/task.md", "status: completed"
    )

    orchestrator.memory_bus.read_exact.return_value = None
    orchestrator.obs_parser.update_status_in_note.reset_mock()
    orchestrator.update_task_status_in_obsidian(
        "Agent Inputs/missing.md", "failed", "missing"
    )
    orchestrator.obs_parser.update_status_in_note.assert_not_called()


def test_sql_status_update_uses_canonical_exact_read_and_reports_pending(
    orchestrator, caplog
):
    """Pending SQL bytes, not stale vault bytes, become the next status revision."""
    orchestrator.memory_bus.sql_store = object()
    orchestrator.obs_manager.read_note.return_value = "status: stale"
    orchestrator.memory_bus.read_exact.return_value = {
        "content": "status: pending\ncanonical: true"
    }
    orchestrator.obs_parser.update_status_in_note.return_value = (
        "status: completed\ncanonical: true"
    )
    orchestrator.memory_bus.write_note_with_embedding.return_value = {
        "status": "accepted",
        "sync_pending": True,
        "obsidian_status": "pending",
        "vector_status": "delivered",
        "idempotency_key": "status-retry-1",
        "event_id": "status-event-1",
    }

    with caplog.at_level("INFO"):
        receipt_state = orchestrator.update_task_status_in_obsidian(
            "Agent Inputs/task.md", "completed", "task-1"
        )

    orchestrator.memory_bus.read_exact.assert_called_once_with("Agent Inputs/task.md")
    orchestrator.obs_parser.update_status_in_note.assert_called_once_with(
        "status: pending\ncanonical: true", "completed", "task-1"
    )
    orchestrator.obs_manager.read_note.assert_not_called()
    assert "Status update accepted" in caplog.text
    assert "projection pending" in caplog.text
    assert "status-retry-1" in caplog.text
    assert "status-event-1" in caplog.text
    assert receipt_state["idempotency_key"] == "status-retry-1"
    assert orchestrator.get_memory_projection_receipt("Agent Inputs/task.md") == (
        receipt_state
    )

    orchestrator.memory_bus.write_note_with_embedding.reset_mock()
    orchestrator.update_task_status_in_obsidian(
        "Agent Inputs/task.md",
        "completed",
        "task-1",
        idempotency_key=receipt_state["idempotency_key"],
    )
    assert (
        orchestrator.memory_bus.write_note_with_embedding.call_args.kwargs[
            "idempotency_key"
        ]
        == "status-retry-1"
    )


def test_sql_status_update_missing_head_does_not_rewrite_stale_vault(orchestrator):
    """A missing canonical task cannot create a revision from orphaned vault bytes."""
    orchestrator.memory_bus.sql_store = object()
    orchestrator.memory_bus.read_exact.return_value = None
    orchestrator.obs_manager.read_note.return_value = "status: stale"

    orchestrator.update_task_status_in_obsidian(
        "Agent Inputs/missing.md", "completed", "missing"
    )

    orchestrator.obs_manager.read_note.assert_not_called()
    orchestrator.obs_parser.update_status_in_note.assert_not_called()
    orchestrator.memory_bus.write_note_with_embedding.assert_not_called()


def test_report_accepted_receipt_records_projection_truth(orchestrator):
    """A durable pending report is recorded as accepted rather than fully synced."""
    orchestrator.memory_bus.write_note_with_embedding.return_value = {
        "status": "accepted",
        "sync_pending": True,
        "obsidian_status": "pending",
        "vector_status": "delivered",
        "idempotency_key": "report-retry-1",
        "event_id": "report-event-1",
    }

    assert (
        orchestrator._persist_agent_report(
            "Report Agent",
            "report-pending",
            {"provenance_id": "run-1"},
            {"status": "success"},
        )
        is True
    )

    persisted = next(
        call
        for call in orchestrator._log_provenance_action.call_args_list
        if call.args[1] == "memory_persisted"
    )
    assert persisted.args[3]["status"] == "accepted"
    assert persisted.args[3]["sync_pending"] is True
    assert persisted.args[3]["obsidian_status"] == "pending"
    assert persisted.args[3]["vector_status"] == "delivered"
    assert persisted.args[3]["idempotency_key"] == "report-retry-1"
    assert persisted.args[3]["event_id"] == "report-event-1"


def test_create_task_accepted_receipt_logs_projection_pending(orchestrator, caplog):
    """Task creation distinguishes canonical acceptance from vault delivery."""
    orchestrator.memory_bus.write_note_with_embedding.return_value = {
        "status": "accepted",
        "sync_pending": True,
        "obsidian_status": "pending",
        "vector_status": "delivered",
        "idempotency_key": "task-retry-1",
        "event_id": "task-event-1",
    }

    with caplog.at_level("INFO"):
        path = orchestrator.create_new_task_in_obsidian(
            {"task_id": "pending-task", "title": "Pending Task"}, "pending.md"
        )

    assert path == "Agent Inputs/pending.md"
    assert "Task note accepted" in caplog.text
    assert "projection pending" in caplog.text
    assert "task-retry-1" in caplog.text
    assert "task-event-1" in caplog.text
    assert "Created new task note in Obsidian" not in caplog.text
    receipt_state = orchestrator.get_memory_projection_receipt(path)
    assert receipt_state["idempotency_key"] == "task-retry-1"

    orchestrator.memory_bus.write_note_with_embedding.reset_mock()
    orchestrator.create_new_task_in_obsidian(
        {"task_id": "pending-task", "title": "Pending Task"},
        "pending.md",
        idempotency_key=receipt_state["idempotency_key"],
    )
    assert (
        orchestrator.memory_bus.write_note_with_embedding.call_args.kwargs[
            "idempotency_key"
        ]
        == "task-retry-1"
    )


def test_raw_artifact_accepted_receipt_tracks_projection_pending(orchestrator):
    """Raw artifact metadata preserves durable-vs-projected receipt state."""
    raw_output = "long raw output" * 4
    orchestrator.exo_summary_threshold_chars = 10
    orchestrator.memory_bus.write_note_with_embedding.return_value = {
        "status": "accepted",
        "sync_pending": True,
        "obsidian_status": "pending",
        "vector_status": "skipped",
    }
    orchestrator.hebbian_router.route.return_value = _Decision("Summarizer Agent")
    orchestrator.assign_and_execute_task = Mock(
        return_value={"status": "failed", "summary": "compression failed"}
    )

    result = orchestrator._compress_long_exo_output(
        {"task_id": "raw-pending", "provenance_id": "prov"},
        {"source_context": {}},
        {
            "status": "success",
            "summary": raw_output,
            "raw_output": raw_output,
            "provider": "exo",
        },
    )

    compression = result["output_compression"]
    assert compression["raw_artifact_persisted"] is True
    assert compression["raw_artifact_status"] == "accepted"
    assert compression["raw_artifact_sync_pending"] is True


def test_sql_memory_failure_logs_no_driver_details(orchestrator, caplog):
    """SQL-mode orchestrator logging never emits a chained driver DSN."""
    from src.integration.sql_memory_store import MemoryStoreError

    orchestrator.memory_bus.sql_store = object()
    orchestrator.memory_bus.write_note_with_embedding.side_effect = MemoryStoreError(
        "driver failed at postgres://fake-secret-host/db"
    )

    with caplog.at_level("ERROR"), pytest.raises(MemoryStoreError):
        orchestrator.create_new_task_in_obsidian(
            {"task_id": "safe-log", "title": "Safe Log"}, "safe-log.md"
        )

    assert "postgres://" not in caplog.text
    assert "canonical memory write failed" in caplog.text.lower()


def test_orchestrator_injects_the_shared_sql_store_factory(monkeypatch):
    """Runtime boot shares the factory store with the memory bus."""
    sql_store = object()
    captured: dict[str, object] = {}
    factory = Mock(return_value=sql_store)

    class FakeMemoryBus:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            self.sql_store = kwargs.get("sql_store")

    registry = SimpleNamespace(get_all_agents=list)
    monkeypatch.setenv("ARTEMIS_MEMORY_DECAY_ENABLED", "0")
    monkeypatch.setattr(orchestrator_module, "create_sql_memory_store", factory)
    obsidian_factory = Mock(
        side_effect=AssertionError("SQL-mode boot must not construct Obsidian eagerly")
    )
    vector_factory = Mock(
        side_effect=AssertionError("SQL-mode boot must not construct vectors eagerly")
    )
    monkeypatch.setattr(orchestrator_module, "ObsidianManager", obsidian_factory)
    monkeypatch.setattr(orchestrator_module, "ObsidianParser", lambda: object())
    monkeypatch.setattr(orchestrator_module, "ObsidianGenerator", lambda: object())
    monkeypatch.setattr(orchestrator_module, "HebbianWeightManager", lambda: object())
    monkeypatch.setattr(orchestrator_module, "create_vector_store", vector_factory)
    monkeypatch.setattr(orchestrator_module, "GovernanceMonitor", lambda: object())
    monkeypatch.setattr(orchestrator_module, "MemoryBus", FakeMemoryBus)
    monkeypatch.setattr(orchestrator_module, "AgentRegistry", lambda: registry)
    monkeypatch.setattr(
        orchestrator_module, "HebbianRouter", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        orchestrator_module,
        "LearningGovernanceCoordinator",
        lambda *args, **kwargs: SimpleNamespace(reconcile_agent=lambda _: None),
    )
    monkeypatch.setattr(orchestrator_module, "CheckpointStore", lambda: object())
    monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: None)
    monkeypatch.setattr(Orchestrator, "_register_agents", lambda self: None)
    monkeypatch.setattr(Orchestrator, "_validate_kernel_state", lambda self: None)
    monkeypatch.setattr(
        "src.integration.trust_interface.TrustInterface", lambda: object()
    )

    instance = Orchestrator()

    factory.assert_called_once_with()
    obsidian_factory.assert_not_called()
    vector_factory.assert_not_called()
    assert instance.memory_bus.sql_store is sql_store
    assert captured["sql_store"] is sql_store


def test_create_task_infers_capability_and_falls_back_to_vault(orchestrator):
    orchestrator.agent_registry.get_agent.return_value = SimpleNamespace(
        capabilities=["research"]
    )
    task = {"task_id": "created-1", "title": "Research Case", "agent": "Research"}

    path = orchestrator.create_new_task_in_obsidian(task, "case.md")

    assert path == "Agent Inputs/case.md"
    serialized = orchestrator.obs_generator.generate_task_note.call_args.args[0]
    assert serialized["required_capability"] == "research"
    assert "required_capability" not in task
    orchestrator.memory_bus.write_note_with_embedding.assert_called_once_with(
        "Agent Inputs/case.md",
        "# Task note",
        metadata={"task_id": "created-1", "created_by": "orchestrator"},
        provenance_id=None,
        source_agent="Artemis Orchestrator",
    )

    orchestrator.memory_bus.write_note_with_embedding.reset_mock()
    orchestrator.memory_bus.write_note_with_embedding.side_effect = OSError(
        "memory unavailable"
    )
    generated_path = orchestrator.create_new_task_in_obsidian(
        {
            "task_id": "created-2",
            "title": "Generated Name",
            "required_capability": "research",
        }
    )
    assert generated_path.startswith("Agent Inputs/generated_name_")
    assert generated_path.endswith(".md")
    orchestrator.obs_manager.write_note.assert_called_once_with(
        generated_path, "# Task note"
    )

    orchestrator.memory_bus.write_note_with_embedding.side_effect = None
    orchestrator.agent_registry.get_agent.return_value = None
    no_capability = {"task_id": "created-3", "title": "Unroutable"}
    path = orchestrator.create_new_task_in_obsidian(no_capability, "unroutable.md")
    assert path == "Agent Inputs/unroutable.md"
    assert "required_capability" not in no_capability


def test_sql_task_write_failure_does_not_fall_back_to_obsidian(orchestrator):
    """An explicit SQL backend cannot be bypassed by a direct vault write."""
    orchestrator.memory_bus.sql_store = object()
    orchestrator.memory_bus.write_note_with_embedding.side_effect = OSError(
        "canonical store unavailable"
    )

    with pytest.raises(OSError, match="canonical store unavailable"):
        orchestrator.create_new_task_in_obsidian(
            {"task_id": "created-4", "title": "SQL Task"}, "sql-task.md"
        )

    orchestrator.obs_manager.write_note.assert_not_called()


def test_sql_report_write_failure_does_not_write_directly_to_obsidian(orchestrator):
    """A canonical report failure leaves no competing direct projection."""
    orchestrator.memory_bus.sql_store = object()
    orchestrator.memory_bus.write_note_with_embedding.side_effect = OSError(
        "canonical store unavailable"
    )

    persisted = orchestrator._persist_agent_report(
        "Report Agent",
        "report-1",
        {"provenance_id": "run-1"},
        {"status": "success"},
    )

    assert persisted is False
    orchestrator.obs_manager.write_note.assert_not_called()


def test_execute_all_pending_tasks_tracks_complete_skip_and_exception(orchestrator):
    pending = [
        (
            "Agent Inputs/ok.md",
            {"task_id": "ok", "required_capability": "research"},
        ),
        ("Agent Inputs/skip.md", {"task_id": "skip"}),
        (
            "Agent Inputs/returned-failure.md",
            {"task_id": "returned-failure", "required_capability": "research"},
        ),
        (
            "Agent Inputs/fail.md",
            {"task_id": "fail", "required_capability": "research"},
        ),
    ]
    orchestrator.check_for_new_tasks_from_obsidian = Mock(return_value=pending)
    orchestrator.update_task_status_in_obsidian = Mock()
    orchestrator.route_and_execute_task = Mock(
        side_effect=[
            {"status": "success", "summary": "done"},
            {
                "status": "failed",
                "summary": "Task could not be completed",
                "error": "model unavailable",
            },
            RuntimeError("agent crashed"),
        ]
    )

    summary = orchestrator.execute_all_pending_tasks()

    assert summary == {
        "total": 4,
        "completed": 1,
        "failed": 2,
        "skipped": 1,
        "details": [
            {"task_id": "ok", "status": "completed"},
            {"task_id": "skip", "status": "skipped", "reason": "no_capability"},
            {
                "task_id": "returned-failure",
                "status": "failed",
                "error": "model unavailable",
            },
            {"task_id": "fail", "status": "failed", "error": "agent crashed"},
        ],
    }
    assert orchestrator.update_task_status_in_obsidian.call_args_list == [
        call("Agent Inputs/ok.md", "in progress", "ok"),
        call("Agent Inputs/skip.md", "no_capability", "skip"),
        call(
            "Agent Inputs/returned-failure.md",
            "in progress",
            "returned-failure",
        ),
        call("Agent Inputs/fail.md", "in progress", "fail"),
        call("Agent Inputs/fail.md", "failed", "fail"),
    ]

    orchestrator.check_for_new_tasks_from_obsidian.return_value = []
    assert orchestrator.execute_all_pending_tasks() == {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }


def test_memory_enrichment_handles_empty_miss_error_and_results(orchestrator):
    # Restore the real helper hidden by the fixture's execution fake.
    enrich = Orchestrator._enrich_task_with_memory.__get__(orchestrator, Orchestrator)
    empty = {"task_id": "empty"}
    assert enrich(empty) is empty

    errored = {"task_id": "error", "content": "query"}
    orchestrator.memory_bus.read.side_effect = OSError("index offline")
    assert enrich(errored) is errored

    missed = {"task_id": "miss", "context": "query"}
    orchestrator.memory_bus.read.side_effect = None
    orchestrator.memory_bus.read.return_value = []
    assert enrich(missed) is missed

    found = {"task_id": "found", "title": "query"}
    retrievals = [{"path": "Agent Outputs/answer.md", "score": 0.8}]
    orchestrator.memory_bus.read.return_value = retrievals
    enriched = enrich(found)
    assert enriched is not found
    assert enriched["memory_context"] == retrievals
    orchestrator.memory_bus.read.assert_called_with("query", max_results=3)


def test_dispatch_preflight_preserves_fallback_and_denies_bad_action(
    orchestrator, monkeypatch
):
    """Sandbox receives the fallback capability and may deny declared actions."""
    allowed = _sandbox_result()
    denied = _sandbox_result(
        False, reason="write blocked", violation_type="tool_denied"
    )
    sandbox = Mock()
    sandbox.check_dispatch.return_value = allowed
    sandbox.check_action.side_effect = [allowed, denied]
    sandbox_type = Mock(return_value=sandbox)
    monkeypatch.setattr(orchestrator_module, "AgentSandbox", sandbox_type)

    agent = SimpleNamespace(
        name="Fallback Agent",
        capabilities=["llm_chat"],
        get_sandbox_policies=lambda: ("not", "a", "list"),
        get_sandbox_actions=lambda _task: [
            "ignore invalid action",
            {"tool_name": "read", "path": "/tmp/source", "operation": "read"},
            {"tool_name": "write", "path": "/etc/passwd", "operation": "write"},
        ],
    )

    result = Orchestrator._check_dispatch(
        orchestrator, agent, {"required_capability": "unavailable"}
    )

    assert result is denied
    assert sandbox_type.call_args.args[:2] == ("Fallback Agent",)
    assert sandbox_type.call_args.kwargs["policies"] == []
    sandbox.check_dispatch.assert_called_once_with("llm_chat")
    assert sandbox.check_action.call_args_list == [
        call("read", path="/tmp/source", operation="read"),
        call("write", path="/etc/passwd", operation="write"),
    ]

    sandbox.reset_mock()
    sandbox.check_dispatch.return_value = denied
    early_denial = Orchestrator._check_dispatch(
        orchestrator, agent, {"required_capability": "unavailable"}
    )
    assert early_denial is denied
    sandbox.check_action.assert_not_called()


def test_hebbian_summary_and_agent_stats_emit_all_metrics(orchestrator, monkeypatch):
    info = Mock()
    monkeypatch.setattr(orchestrator_module.logger, "info", info)
    orchestrator.hebbian.get_network_summary.return_value = {
        "total_connections": 4,
        "average_weight": 1.25,
        "max_weight": 2.5,
        "total_activations": 9,
        "success_rate": 0.75,
    }
    orchestrator.hebbian.get_agent_average_weight.return_value = 1.5
    orchestrator.hebbian.get_agent_success_rate.return_value = 0.8
    orchestrator.hebbian.get_strongest_connections.return_value = [
        ("research", 2.0),
        ("analysis", 1.25),
    ]

    orchestrator.show_hebbian_network_summary()
    orchestrator.show_agent_hebbian_stats("Research Agent\n")

    assert call("Total Connections: %s", 4) in info.call_args_list
    assert call("Success Rate: %.2f%%", 75.0) in info.call_args_list
    assert call("Average Weight: %.2f", 1.5) in info.call_args_list
    assert call("Success Rate: %.2f%%", 80.0) in info.call_args_list
    assert call("  %s. %s (weight: %.1f)", 1, "research", 2.0) in info.call_args_list
    assert call("  %s. %s (weight: %.1f)", 2, "analysis", 1.25) in info.call_args_list
    orchestrator.hebbian.get_strongest_connections.assert_called_once_with(
        "Research Agent\n", limit=10
    )


def test_hebbian_update_surfaces_sentinel_and_merges_governance(orchestrator):
    orchestrator.hebbian.record_outcome.return_value = {
        "weight": 1.7,
        "delta": -0.2,
        "task_type": "research",
        "sentinel_alert": True,
        "oscillation_rate": 0.55,
        "sentinel_samples": 12,
    }
    orchestrator.learning_governance.record_execution_outcome.return_value = {
        "trust_score": 0.72,
        "execution_count": 4,
    }

    update = Orchestrator._update_hebbian_weights.__get__(orchestrator, Orchestrator)
    result = update(
        "Research Agent",
        "sentinel-task",
        True,
        task_type="research",
        results={"quality_score": 75},
        duration_ms=12.5,
    )

    orchestrator.hebbian.record_outcome.assert_called_once_with(
        "Research Agent",
        "sentinel-task",
        success=True,
        performance=0.75,
        task_type="research",
        duration_ms=12.5,
    )
    assert result["sentinel_alert"] is True
    assert result["trust_score"] == pytest.approx(0.72)


def test_provenance_logger_laziness_and_fail_closed_behavior(orchestrator, monkeypatch):
    run_logger = Mock()
    run_logger.log_event.return_value = "child-event"
    monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: run_logger)
    task = {"task_id": "prov"}

    event_id = Orchestrator._log_provenance_action(
        orchestrator,
        task,
        "action",
        "component",
        {"safe": True},
        "done",
        3.5,
    )

    assert event_id == "child-event"
    assert task["provenance_id"]
    assert run_logger.log_event.call_args.kwargs["parent_prov_id"] == str(
        task["provenance_id"]
    )

    monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: None)
    assert (
        Orchestrator._log_provenance_action(
            orchestrator,
            {"task_id": "optional", "provenance_id": "parent"},
            "action",
            "component",
        )
        is None
    )
    with pytest.raises(RuntimeError, match="provenance sink is unavailable"):
        Orchestrator._log_provenance_action(
            orchestrator,
            {"atp": {"mode": "Build"}, "provenance_id": "parent"},
            "action",
            "component",
        )


def test_kernel_validation_handles_empty_and_malformed_agents(
    orchestrator, monkeypatch
):
    error = Mock()
    warning = Mock()
    monkeypatch.setattr(orchestrator_module.logger, "error", error)
    monkeypatch.setattr(orchestrator_module.logger, "warning", warning)

    orchestrator.agent_registry.get_agent_names.return_value = []
    Orchestrator._validate_kernel_state(orchestrator)
    error.assert_called_once()

    orchestrator.agent_registry.get_agent_names.return_value = ["Metadata Only"]
    orchestrator.agent_registry.get_all_agents.return_value = [
        SimpleNamespace(name="Metadata Only")
    ]
    Orchestrator._validate_kernel_state(orchestrator)
    warning.assert_called_once()
    assert Orchestrator._resolve_required_capability(orchestrator, "not-a-dict") is None


def test_run_logger_loader_caches_success_and_swallows_failure(monkeypatch):
    import src.utils as utils

    sentinel = object()
    loader = Mock(return_value=sentinel)
    monkeypatch.setattr(utils, "get_run_logger", loader)
    monkeypatch.setattr(orchestrator_module, "_run_logger", None)

    assert orchestrator_module._get_run_logger() is sentinel
    assert orchestrator_module._get_run_logger() is sentinel
    loader.assert_called_once_with()

    monkeypatch.setattr(orchestrator_module, "_run_logger", None)
    loader.side_effect = RuntimeError("store unavailable")
    assert orchestrator_module._get_run_logger() is None


def test_optional_anaconda_registration_is_non_blocking(orchestrator, monkeypatch):
    import src.integration.anaconda_stack as anaconda_stack

    for constructor_name in (
        "ArtemisAgent",
        "ResearchAgent",
        "SummarizerAgent",
        "LLMAgent",
    ):
        monkeypatch.setattr(
            orchestrator_module,
            constructor_name,
            Mock(return_value=SimpleNamespace(name=constructor_name)),
        )

    register = Mock(return_value=["Studio Agent"])
    monkeypatch.setattr(anaconda_stack, "register_anaconda_stack", register)
    Orchestrator._register_agents(orchestrator)

    register.side_effect = ModuleNotFoundError("requests missing", name="requests")
    Orchestrator._register_agents(orchestrator)

    register.side_effect = ModuleNotFoundError("other missing", name="other_package")
    Orchestrator._register_agents(orchestrator)

    register.side_effect = RuntimeError("studio offline")
    Orchestrator._register_agents(orchestrator)
    assert orchestrator.agent_registry.register_agent.call_count == 16


def test_boot_degrades_cleanly_when_optional_services_fail(monkeypatch):
    """Invalid tuning, decay failure, and trust failure must not prevent boot."""
    memory_bus = Mock()
    memory_bus.run_memory_decay_cycle.side_effect = RuntimeError("decay unavailable")
    registry = Mock()
    registry.get_all_agents.return_value = []
    router_type = Mock()

    simple_types = {
        "ObsidianManager": Mock(),
        "ObsidianParser": Mock(),
        "ObsidianGenerator": Mock(),
        "HebbianWeightManager": Mock(),
        "GovernanceMonitor": Mock(),
        "MemoryDecayService": Mock(),
        "MemoryBus": Mock(return_value=memory_bus),
        "AgentRegistry": Mock(return_value=registry),
        "HebbianRouter": router_type,
        "LearningGovernanceCoordinator": Mock(),
        "CheckpointStore": Mock(),
    }
    for name, replacement in simple_types.items():
        monkeypatch.setattr(orchestrator_module, name, replacement)
    monkeypatch.setattr(Orchestrator, "_register_agents", Mock())
    monkeypatch.setattr(Orchestrator, "_ensure_obsidian_agent_dirs", Mock())
    monkeypatch.setattr(Orchestrator, "_validate_kernel_state", Mock())
    monkeypatch.setattr(orchestrator_module, "_get_run_logger", lambda: None)
    monkeypatch.setenv("ARTEMIS_HEBBIAN_ROUTING_ALPHA", "invalid")
    monkeypatch.setenv("ARTEMIS_HEBBIAN_ROUTING_BETA", "invalid")
    monkeypatch.setenv("ARTEMIS_ROUTING_TRUST_FLOOR", "invalid")

    import src.integration.trust_interface as trust_module

    monkeypatch.setattr(
        trust_module,
        "TrustInterface",
        Mock(side_effect=RuntimeError("trust unavailable")),
    )

    instance = Orchestrator(vector_store=Mock())

    assert instance.trust_interface is None
    assert router_type.call_args.kwargs["alpha"] == pytest.approx(0.3)
    assert router_type.call_args.kwargs["beta"] == pytest.approx(0.0)
    assert router_type.call_args.kwargs["trust_floor"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("results", "success", "expected"),
    [
        ({}, False, 0.0),
        ({}, True, 1.0),
        ({"quality_score": 88}, True, 0.88),
        ({"confidence": 2.0}, True, 0.02),
        ({"score": -3}, True, 0.0),
        ({"metrics": {"performance": 1.5}}, True, 0.015),
        ({"performance_score": True, "metrics": {"quality": 0.6}}, True, 0.6),
    ],
)
def test_outcome_performance_normalizes_available_quality_signal(
    results, success, expected
):
    assert Orchestrator._outcome_performance(results, success) == pytest.approx(
        expected
    )
