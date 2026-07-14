"""Endpoint-free edge coverage for :mod:`src.agents.llm_agent`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.agents.llm_agent as llm_module
from src.agents.llm_agent import DEFAULT_EXO_MODEL_ID, LLMAgent, _MissingRequests


class _HTTPError(RuntimeError):
    """Small requests-compatible error carrying an HTTP response status."""

    def __init__(self, status_code: int, message: str = "request failed") -> None:
        super().__init__(message)
        self.response = SimpleNamespace(status_code=status_code)


def _response(
    *,
    body: dict | None = None,
    lines: list[str | bytes] | None = None,
    error: Exception | None = None,
) -> Mock:
    response = Mock()
    response.json.return_value = body or {}
    response.iter_lines.return_value = iter(lines or [])
    response.raise_for_status.side_effect = error
    return response


def _agent(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> LLMAgent:
    monkeypatch.delenv("EXO_API_KEY", raising=False)
    return LLMAgent(
        base_url="http://exo.test:52415",
        model_id="test-model",
        **kwargs,
    )


def test_missing_requests_adapter_and_import_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optional dependency failure remains explicit for POST and GET."""
    missing = _MissingRequests()
    with pytest.raises(RuntimeError, match="requests.*not installed"):
        missing.post("http://never-called.test")
    with pytest.raises(RuntimeError, match="requests.*not installed"):
        missing.get("http://never-called.test")

    # Load the module under an alias while making only ``requests`` unavailable.
    # This exercises the actual import fallback without disturbing the live module.
    monkeypatch.setitem(sys.modules, "requests", None)
    module_path = Path(llm_module.__file__)
    spec = importlib.util.spec_from_file_location(
        "src.agents._llm_agent_without_requests", module_path
    )
    assert spec is not None and spec.loader is not None
    imported = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imported)
    assert type(imported.requests).__name__ == "_MissingRequests"


def test_environment_configuration_and_sandbox_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXO_MODEL_URL", "https://exo.example/v1/responses")
    monkeypatch.setenv("EXO_BASE_URL", "https://ignored.example")
    monkeypatch.setenv("EXO_MODEL_ID", " env-model ")
    monkeypatch.setenv("EXO_API_KEY", " secret ")

    agent = LLMAgent()

    assert agent.model_url == "https://exo.example/v1"
    assert agent.model_id == "env-model"
    assert agent.api_key == "secret"
    policy = agent.get_sandbox_policies()[0]
    assert policy.name == "exo_http"
    assert policy.paths == ["https://exo.example/**"]
    assert policy.operations == ["chat"]
    assert agent.get_sandbox_actions(
        {"model_url": "https://exo.example/v1/chat/completions"}
    ) == [
        {
            "tool_name": "exo_http",
            "path": "https://exo.example/v1",
            "operation": "chat",
        }
    ]


def test_message_normalization_filters_invalid_items_and_falls_back_to_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    assert agent._build_messages(
        {
            "messages": [
                None,
                {"content": "  "},
                {"role": "assistant", "content": " ready "},
                {"content": " default role "},
            ]
        }
    ) == [
        {"role": "assistant", "content": "ready"},
        {"role": "user", "content": "default role"},
    ]
    assert agent._build_messages(
        {
            "messages": [None, {"content": ""}],
            "content": " fallback prompt ",
            "system_prompt": " system ",
        }
    ) == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "fallback prompt"},
    ]


@pytest.mark.parametrize("field", ["prompt", "content", "context", "query"])
def test_supported_prompt_aliases(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    agent = _agent(monkeypatch)
    assert agent._build_messages({field: "question"}) == [
        {"role": "user", "content": "question"}
    ]


def test_model_resolution_prefers_task_then_authenticated_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXO_MODEL_ID", "")
    monkeypatch.setenv("EXO_API_KEY", "token")
    agent = LLMAgent(base_url="http://exo.test:52415", timeout_seconds=9)
    assert agent._resolve_model({"model": " task-model "}, agent.model_url) == (
        "task-model"
    )

    running = _response(
        body={
            "models": [
                "invalid",
                {"model": ""},
                {"name": ""},
                {"id": " discovered-model "},
            ]
        }
    )
    get = Mock(return_value=running)
    monkeypatch.setattr(llm_module.requests, "get", get)

    assert agent._resolve_model({}, agent.model_url) == "discovered-model"
    assert get.call_args.args == ("http://exo.test:52415/ollama/api/ps",)
    assert get.call_args.kwargs == {
        "headers": {"Authorization": "Bearer token"},
        "timeout": 2.0,
    }


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"models": "not-a-list"}, None),
        ({"models": []}, RuntimeError("discovery unavailable")),
    ],
)
def test_model_discovery_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch,
    body: dict,
    error: Exception | None,
) -> None:
    monkeypatch.setenv("EXO_MODEL_ID", "")
    agent = LLMAgent(base_url="http://exo.test:52415")
    response = _response(body=body, error=error)
    monkeypatch.setattr(llm_module.requests, "get", Mock(return_value=response))

    assert agent._resolve_model({}, agent.model_url) == DEFAULT_EXO_MODEL_ID


def test_completion_candidates_keep_endpoint_order_and_payload_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    messages = [{"role": "user", "content": "hello"}]

    candidates = agent._completion_request_candidates(
        messages, "test-model", 0.4, 123, "http://exo.test:52415/v1", stream=True
    )

    assert [candidate[0] for candidate in candidates] == [
        "http://exo.test:52415/v1/chat/completions",
        "http://exo.test:52415/v1/responses",
    ]
    assert candidates[0][1] == {
        "model": "test-model",
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 123,
        "stream": True,
    }
    assert candidates[1][1] == {
        "model": "test-model",
        "input": messages,
        "temperature": 0.4,
        "max_output_tokens": 123,
        "stream": True,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [(400, True), (404, True), (405, True), (422, True), (401, False), (500, False)],
)
def test_endpoint_retry_is_limited_to_compatibility_statuses(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: bool
) -> None:
    agent = _agent(monkeypatch)
    assert agent._should_try_next_endpoint(_HTTPError(status)) is expected
    assert agent._should_try_next_endpoint(RuntimeError("transport")) is False


def test_nonstreaming_fallback_uses_responses_output_text_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    agent.api_key = "api-key"
    missing_chat = _response(error=_HTTPError(422, "chat shape rejected"))
    responses = _response(
        body={
            "id": "response-id",
            "output_text": " response text ",
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }
    )
    post = Mock(side_effect=[missing_chat, responses])
    monkeypatch.setattr(llm_module.requests, "post", post)

    result = agent.perform_task(
        {"prompt": "hello", "temperature": 0.7, "max_tokens": 99}
    )

    assert result == {
        "status": "success",
        "summary": "response text",
        "provider": "exo",
        "model": "test-model",
        "model_url": "http://exo.test:52415/v1",
        "usage": {"input_tokens": 2, "output_tokens": 3},
        "response_id": "response-id",
    }
    assert [call.args[0] for call in post.call_args_list] == [
        "http://exo.test:52415/v1/chat/completions",
        "http://exo.test:52415/v1/responses",
    ]
    assert post.call_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer api-key"
    )


def test_nonstreaming_does_not_retry_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    server_error = _response(error=_HTTPError(500, "server failed"))
    post = Mock(return_value=server_error)
    monkeypatch.setattr(llm_module.requests, "post", post)

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "failed"
    assert "chat/completions" in result["llm_error"]
    assert "responses" not in result["llm_error"]
    post.assert_called_once()


def test_nonstreaming_both_compatible_endpoints_can_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    post = Mock(
        side_effect=[
            _response(error=_HTTPError(404, "chat missing")),
            _response(error=_HTTPError(405, "responses disabled")),
        ]
    )
    monkeypatch.setattr(llm_module.requests, "post", post)

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "failed"
    assert "chat missing" in result["llm_error"]
    assert "responses disabled" in result["llm_error"]
    assert post.call_count == 2


def test_nonstreaming_rejects_a_successful_but_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    post = Mock(
        side_effect=[
            _response(error=_HTTPError(404)),
            _response(body={"choices": [{"message": {"content": ""}}]}),
        ]
    )
    monkeypatch.setattr(llm_module.requests, "post", post)

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "failed"
    assert "no text content" in result["llm_error"]


def test_missing_requests_dependency_returns_normalized_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    monkeypatch.setattr(llm_module, "requests", _MissingRequests())

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "failed"
    assert result["provider"] == "fallback"
    assert "requests' package is not installed" in result["llm_error"]


def test_response_parser_handles_nested_responses_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    body = {
        "output": [
            None,
            {"content": "not-a-list"},
            {
                "content": [
                    None,
                    {"type": "metadata", "text": "ignored"},
                    {"type": "text", "text": "  "},
                    {"type": "output_text", "text": " first "},
                ]
            },
            {"content": [{"type": "text", "text": "second"}]},
        ]
    }

    assert agent._extract_message_content(body) == "first second"


def test_response_parser_falls_through_empty_output_to_chat_content_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    body = {
        "output": [{"content": [{"type": "metadata", "text": "ignored"}]}],
        "choices": [
            {
                "message": {
                    "content": [
                        None,
                        {"type": "metadata", "text": "ignored"},
                        {"type": "text", "text": "hello"},
                        {"type": "text", "text": "world"},
                    ]
                }
            }
        ],
    }

    assert agent._extract_message_content(body) == "hello world"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "", "reasoning_content": "thought"},
                    }
                ]
            },
            "[Model hit max_tokens during reasoning — increase max_tokens to get "
            "a final answer.]\n\nthought",
        ),
        (
            {"choices": [{"message": {"content": "", "reasoning_content": "thought"}}]},
            "[Model reasoning only — no final content emitted.]\n\nthought",
        ),
        (
            {"choices": [{"message": {"content": ""}, "text": "legacy"}]},
            "legacy",
        ),
        ({"choices": [{"message": {"content": ""}}]}, ""),
        ({"choices": [{"message": "invalid", "text": "root text"}]}, "root text"),
        ({"choices": ["invalid"]}, ""),
    ],
)
def test_response_parser_chat_variants(
    monkeypatch: pytest.MonkeyPatch, body: dict, expected: str
) -> None:
    agent = _agent(monkeypatch)
    assert agent._extract_message_content(body) == expected


def test_response_parser_requires_choices_after_empty_responses_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    with pytest.raises(ValueError, match="No choices"):
        agent._extract_message_content({"output": [{"content": []}]})


def test_streaming_falls_back_to_responses_sse_without_duplicate_final_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    missing_chat = _response(error=_HTTPError(404, "chat route missing"))
    responses = _response(
        lines=[
            "event: response.output_text.delta",
            'data: {"type":"response.output_text.delta","delta":"Hello"}',
            'data: {"type":"response.output_text.delta","delta":" world"}',
            'data: {"type":"response.output_text.done","text":"Hello world"}',
            'data: {"type":"response.completed","response":{"output_text":"Hello world"}}',
            "data: [DONE]",
        ]
    )
    post = Mock(side_effect=[missing_chat, responses])
    monkeypatch.setattr(llm_module.requests, "post", post)

    events = list(agent.stream_task({"prompt": "hello", "max_tokens": 12}))

    assert [event["text"] for event in events if event["type"] == "token"] == [
        "Hello",
        " world",
    ]
    assert events[-1] == {
        "type": "final",
        "result": {
            "status": "success",
            "summary": "Hello world",
            "provider": "exo",
            "model": "test-model",
            "model_url": "http://exo.test:52415/v1",
        },
    }
    assert [call.args[0] for call in post.call_args_list] == [
        "http://exo.test:52415/v1/chat/completions",
        "http://exo.test:52415/v1/responses",
    ]
    assert post.call_args_list[1].kwargs["json"]["input"] == [
        {"role": "user", "content": "hello"}
    ]
    assert post.call_args_list[1].kwargs["json"]["max_output_tokens"] == 12
    missing_chat.close.assert_called_once_with()
    responses.close.assert_called_once_with()


def test_streaming_responses_completed_event_can_supply_the_only_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    post = Mock(
        side_effect=[
            _response(error=_HTTPError(405)),
            _response(
                lines=[
                    'data: {"type":"response.completed","response":{"output_text":"final only"}}',
                    "data: [DONE]",
                ]
            ),
        ]
    )
    monkeypatch.setattr(llm_module.requests, "post", post)

    events = list(agent.stream_task({"prompt": "hello"}))

    assert [event["text"] for event in events if event["type"] == "token"] == [
        "final only"
    ]
    assert events[-1]["result"]["summary"] == "final only"


def test_streaming_retries_when_post_itself_raises_compatible_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    responses = _response(
        lines=[
            'data: {"type":"response.output_text.delta","delta":"recovered"}',
            "data: [DONE]",
        ]
    )
    post = Mock(side_effect=[_HTTPError(404, "chat absent"), responses])
    monkeypatch.setattr(llm_module.requests, "post", post)

    events = list(agent.stream_task({"prompt": "hello"}))

    assert events[0] == {"type": "token", "text": "recovered"}
    assert events[-1]["result"]["status"] == "success"
    responses.close.assert_called_once_with()


def test_streaming_both_compatible_endpoints_fail_with_one_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    post = Mock(
        side_effect=[
            _response(error=_HTTPError(404, "chat absent")),
            _response(error=_HTTPError(422, "responses rejected")),
        ]
    )
    monkeypatch.setattr(llm_module.requests, "post", post)

    events = list(agent.stream_task({"prompt": "hello"}))

    assert [event["type"] for event in events] == ["token", "final"]
    result = events[-1]["result"]
    assert result["status"] == "failed"
    assert result["provider"] == "fallback"
    assert "chat absent" in result["llm_error"]
    assert "responses rejected" in result["llm_error"]
    assert post.call_count == 2


def test_chat_sse_parser_handles_bytes_blanks_lists_and_final_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    agent.api_key = "api-key"
    response = _response(
        lines=[
            b"",
            b": keep-alive",
            b"data:",
            b"data: not-json",
            b'data: {"choices":[{"delta":{"content":[{"type":"other","text":"x"},{"type":"text","text":"A"},{"type":"text","text":"B"}]}}]}',
            'data: {"choices":["invalid"]}',
            'data: {"choices":[{"message":{"content":"C"}}]}',
            "data: [DONE]",
        ]
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(llm_module.requests, "post", post)

    pieces = list(
        agent._stream_exo(
            [{"role": "user", "content": "hello"}],
            "test-model",
            0.2,
            8,
            agent.model_url,
        )
    )

    assert pieces == ["AB", "C"]
    assert post.call_args.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Authorization": "Bearer api-key",
    }
    response.close.assert_called_once_with()


def test_empty_successful_stream_uses_failed_final_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    response = _response(lines=[])
    monkeypatch.setattr(llm_module.requests, "post", Mock(return_value=response))

    events = list(agent.stream_task({"prompt": "hello"}))

    assert [event["type"] for event in events] == ["token", "final"]
    assert events[-1]["result"]["status"] == "failed"
    assert events[-1]["result"]["llm_error"] == "Exo stream produced no content"
    response.close.assert_called_once_with()


def test_stream_failure_after_partial_content_does_not_claim_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    def broken_stream(*_args: object, **_kwargs: object):
        yield ""
        yield "partial"
        raise RuntimeError("connection dropped")

    monkeypatch.setattr(agent, "_stream_exo", broken_stream)

    events = list(agent.stream_task({"prompt": "hello"}))

    assert events[0] == {"type": "token", "text": "partial"}
    assert events[1]["type"] == "token"
    assert events[-1]["type"] == "final"
    assert events[-1]["result"]["status"] == "failed"
    assert events[-1]["result"]["llm_error"] == "connection dropped"


def test_sse_response_is_closed_when_iteration_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    response = _response()
    response.iter_lines.side_effect = RuntimeError("stream read failed")
    monkeypatch.setattr(llm_module.requests, "post", Mock(return_value=response))

    events = list(agent.stream_task({"prompt": "hello"}))

    assert events[-1]["result"]["status"] == "failed"
    assert "stream read failed" in events[-1]["result"]["llm_error"]
    response.close.assert_called_once_with()


def test_delta_parser_rejects_malformed_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    assert agent._extract_delta_content({}) == ""
    assert agent._extract_delta_content({"choices": "invalid"}) == ""
    assert agent._extract_delta_content({"choices": ["invalid"]}) == ""
    assert (
        agent._extract_delta_content(
            {"choices": [{"delta": {"content": 7}, "message": {"content": 8}}]}
        )
        == ""
    )
    assert (
        agent._extract_delta_content({"type": "response.output_text.delta", "delta": 8})
        == ""
    )
    assert (
        agent._extract_delta_content({"type": "response.output_text.done", "text": 8})
        == ""
    )
    assert (
        agent._extract_delta_content(
            {"type": "response.completed", "response": "invalid"}
        )
        == ""
    )
    assert (
        agent._extract_delta_content({"type": "response.completed", "response": {}})
        == ""
    )
