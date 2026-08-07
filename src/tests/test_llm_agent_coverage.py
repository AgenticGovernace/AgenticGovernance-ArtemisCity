"""Endpoint-free edge coverage for :mod:`src.agents.llm_agent`."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.agents.llm_agent as llm_module
from src.agents.llm_agent import (DEFAULT_EXO_MODEL_ID, LLMAgent,
                                  _MissingRequests)


class _HTTPError(RuntimeError):
    """Small requests-compatible error carrying an HTTP response status."""

    def __init__(self, status_code: int, message: str = "request failed") -> None:
        super().__init__(message)
        self.response = SimpleNamespace(status_code=status_code)


class ReadTimeout(RuntimeError):
    """Requests-like read timeout used without an external endpoint."""


def _response(
    *,
    body: dict | None = None,
    lines: list[str | bytes] | None = None,
    error: Exception | None = None,
) -> Mock:
    response = Mock()
    response.status_code = (
        getattr(getattr(error, "response", None), "status_code", 200)
        if error is not None
        else 200
    )
    response.headers = {}
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


def test_timeout_and_retry_configuration_supports_env_legacy_and_no_read_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXO_CONNECT_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("EXO_READ_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("EXO_MAX_RETRIES", "4")
    monkeypatch.setenv("EXO_RETRY_BACKOFF_SECONDS", "0.25")
    monkeypatch.setenv("EXO_RETRY_MAX_DELAY_SECONDS", "9")

    configured = LLMAgent(base_url="http://exo.test:52415", model_id="model")
    assert configured.request_timeout == (3.5, None)
    assert configured.timeout_seconds == 0.0
    assert configured.max_retries == 4
    assert configured.retry_backoff_seconds == 0.25
    assert configured.retry_max_delay_seconds == 9.0

    legacy = LLMAgent(
        base_url="http://exo.test:52415", model_id="model", timeout_seconds=7
    )
    assert legacy.request_timeout == (7.0, 7.0)
    assert legacy.timeout_seconds == 7.0

    split = LLMAgent(
        base_url="http://exo.test:52415",
        model_id="model",
        timeout_seconds=7,
        connect_timeout_seconds=2,
        read_timeout_seconds=0,
    )
    assert split.request_timeout == (2.0, None)


def test_invalid_timeout_and_retry_environment_values_use_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXO_CONNECT_TIMEOUT_SECONDS", "bad")
    monkeypatch.setenv("EXO_READ_TIMEOUT_SECONDS", "bad")
    monkeypatch.setenv("EXO_MAX_RETRIES", "bad")

    agent = LLMAgent(base_url="http://exo.test:52415", model_id="model")

    assert agent.request_timeout == (10.0, 900.0)
    assert agent.max_retries == 2


def test_optional_response_headers_and_http_date_retry_after_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    assert agent._server_request_id(SimpleNamespace(headers=None)) is None

    parser = Mock(
        side_effect=[
            llm_module.datetime(2099, 1, 1),
            ValueError("invalid HTTP date"),
        ]
    )
    monkeypatch.setattr(llm_module, "parsedate_to_datetime", parser)

    delay = agent._retry_after_seconds(
        SimpleNamespace(headers={"Retry-After": "future-date"})
    )
    assert delay is not None and delay > 0
    assert (
        agent._retry_after_seconds(
            SimpleNamespace(headers={"Retry-After": "invalid-date"})
        )
        is None
    )


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

    assert result["status"] == "success"
    assert result["summary"] == "response text"
    assert result["raw_output"] == "response text"
    assert result["provider"] == "exo"
    assert result["model"] == "test-model"
    assert result["model_url"] == "http://exo.test:52415/v1"
    assert result["usage"] == {"input_tokens": 2, "output_tokens": 3}
    assert result["response_id"] == "response-id"
    assert result["exo_request"]["endpoint"] == ("http://exo.test:52415/v1/responses")
    assert result["exo_request"]["attempt_count"] == 2
    assert [call.args[0] for call in post.call_args_list] == [
        "http://exo.test:52415/v1/chat/completions",
        "http://exo.test:52415/v1/responses",
    ]
    assert post.call_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer api-key"
    )
    assert "api-key" not in repr(result["exo_request"])


def test_nonstreaming_success_exposes_correlatable_wire_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    response = _response(
        body={
            "id": "exo-response-42",
            "model": "actual-running-model",
            "choices": [{"message": {"content": "verifiable output"}}],
        }
    )
    response.headers = {"X-Request-ID": "exo-server-request-9"}
    post = Mock(return_value=response)
    monkeypatch.setattr(llm_module.requests, "post", post)
    monkeypatch.setattr(llm_module.uuid, "uuid4", Mock(return_value="artemis-req-1"))

    result = agent.perform_task({"prompt": "hello"})

    assert result["summary"] == "verifiable output"
    assert result["raw_output"] == result["summary"]
    wire = result["exo_request"]
    assert wire["request_id"] == "artemis-req-1"
    assert wire["server_request_id"] == "exo-server-request-9"
    assert wire["endpoint"] == "http://exo.test:52415/v1/chat/completions"
    assert wire["http_status"] == 200
    assert wire["requested_model"] == "test-model"
    assert wire["response_id"] == "exo-response-42"
    assert wire["response_model"] == "actual-running-model"
    assert wire["content_length"] == len("verifiable output")
    assert wire["content_sha256"] == hashlib.sha256(b"verifiable output").hexdigest()
    assert wire["attempt_count"] == 1
    assert wire["attempts"][0]["outcome"] == "success"
    assert post.call_args.kwargs["timeout"] == (10.0, 900.0)
    assert post.call_args.kwargs["headers"]["X-Request-ID"] == wire["request_id"]


def test_rate_limit_retries_respect_retry_after_and_keep_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        monkeypatch,
        max_retries=2,
        retry_backoff_seconds=0.1,
        retry_max_delay_seconds=10,
    )
    limited = _response(error=_HTTPError(429, "slow down"))
    limited.headers = {"Retry-After": "2.5"}
    success = _response(body={"choices": [{"message": {"content": "after wait"}}]})
    post = Mock(side_effect=[limited, success])
    sleep = Mock()
    monkeypatch.setattr(llm_module.requests, "post", post)
    monkeypatch.setattr(llm_module.time, "sleep", sleep)

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "success"
    assert result["raw_output"] == "after wait"
    assert post.call_count == 2
    sleep.assert_called_once_with(2.5)
    request_ids = [
        call.kwargs["headers"]["X-Request-ID"] for call in post.call_args_list
    ]
    assert len(set(request_ids)) == 1
    wire = result["exo_request"]
    assert wire["attempt_count"] == 2
    assert wire["attempts"][0]["failure_kind"] == "rate_limited"
    assert wire["attempts"][0]["retry_after_seconds"] == 2.5
    assert wire["attempts"][0]["retry_delay_seconds"] == 2.5


def test_exhausted_rate_limit_exposes_upstream_retry_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch, max_retries=0)
    limited = _response(error=_HTTPError(429, "slow down"))
    limited.headers = {"Retry-After": "7"}
    monkeypatch.setattr(llm_module.requests, "post", Mock(return_value=limited))

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "failed"
    assert result["failure_kind"] == "rate_limited"
    assert result["retry_after_seconds"] == 7.0
    assert result["exo_request"]["retry_after_seconds"] == 7.0


def test_transient_retries_are_bounded_and_provider_failure_is_not_learnable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        monkeypatch,
        max_retries=1,
        retry_backoff_seconds=0,
    )
    unavailable = _response(error=_HTTPError(503, "exo loading model"))
    post = Mock(return_value=unavailable)
    monkeypatch.setattr(llm_module.requests, "post", post)

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "failed"
    assert result["provider"] == "exo"
    assert result["fallback_used"] is False
    assert result["outcome_class"] == "provider_failure"
    assert result["learning_eligible"] is False
    assert result["failure_kind"] == "http_error"
    assert result["retryable"] is True
    assert result["upstream_status_code"] == 503
    assert result["attempt_count"] == 2
    assert result["exo_request"]["attempt_count"] == 2
    assert post.call_count == 2


def test_connect_failures_retry_but_read_timeouts_do_not_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        monkeypatch,
        max_retries=2,
        retry_backoff_seconds=0,
    )
    success = _response(body={"choices": [{"message": {"content": "connected"}}]})
    post = Mock(side_effect=[ConnectionError("connection refused"), success])
    monkeypatch.setattr(llm_module.requests, "post", post)

    result = agent.perform_task({"prompt": "hello"})

    assert result["status"] == "success"
    assert result["exo_request"]["attempt_count"] == 2
    assert result["exo_request"]["attempts"][0]["failure_kind"] == ("connect_timeout")

    read_timeout_post = Mock(side_effect=ReadTimeout("read timed out"))
    monkeypatch.setattr(llm_module.requests, "post", read_timeout_post)
    failed = agent.perform_task({"prompt": "hello"})

    assert failed["status"] == "failed"
    assert failed["failure_kind"] == "read_timeout"
    assert failed["retryable"] is False
    assert failed["attempt_count"] == 1
    read_timeout_post.assert_called_once()


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
    assert result["provider"] == "exo"
    assert result["fallback_used"] is False
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
    final = events[-1]
    assert final["type"] == "final"
    assert final["result"]["status"] == "success"
    assert final["result"]["summary"] == "Hello world"
    assert final["result"]["raw_output"] == "Hello world"
    assert final["result"]["provider"] == "exo"
    assert final["result"]["model"] == "test-model"
    assert final["result"]["model_url"] == "http://exo.test:52415/v1"
    assert final["result"]["exo_request"]["endpoint"] == (
        "http://exo.test:52415/v1/responses"
    )
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


def test_reasoning_only_response_is_not_reported_as_successful_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    monkeypatch.setattr(
        agent,
        "_call_exo",
        lambda *_args, **_kwargs: {
            "content": (
                "[Model hit max_tokens during reasoning — increase max_tokens "
                "to get a final answer.]\n\nThinking about the judgment..."
            ),
            "exo_request": {"request_id": "req-1"},
        },
    )

    result = agent.perform_task({"prompt": "Summarize this judgment."})

    assert result["status"] == "failed"
    assert result["outcome_class"] == "provider_failure"
    assert result["learning_eligible"] is False
    assert result["summary"] == (
        "[Model hit max_tokens during reasoning; no final answer emitted.]"
    )


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


def test_streaming_final_preserves_exact_output_and_wire_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    response = _response(
        lines=[
            'data: {"id":"stream-7","model":"running-model","choices":[{"delta":{"content":" leading"}}]}',
            'data: {"choices":[{"delta":{"content":" and trailing "}}]}',
            "data: [DONE]",
        ]
    )
    response.headers = {"X-Request-ID": "exo-stream-server-2"}
    post = Mock(return_value=response)
    monkeypatch.setattr(llm_module.requests, "post", post)
    monkeypatch.setattr(llm_module.uuid, "uuid4", Mock(return_value="stream-req-1"))

    events = list(agent.stream_task({"prompt": "hello"}))

    final = events[-1]["result"]
    assert final["status"] == "success"
    assert final["summary"] == " leading and trailing "
    assert final["raw_output"] == final["summary"]
    wire = final["exo_request"]
    assert wire["request_id"] == "stream-req-1"
    assert wire["server_request_id"] == "exo-stream-server-2"
    assert wire["http_status"] == 200
    assert wire["response_id"] == "stream-7"
    assert wire["response_model"] == "running-model"
    assert wire["content_length"] == len(final["raw_output"])
    assert (
        wire["content_sha256"]
        == hashlib.sha256(final["raw_output"].encode()).hexdigest()
    )
    assert post.call_args.kwargs["timeout"] == (10.0, 900.0)


def test_streaming_retries_transient_pre_response_failure_without_id_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        monkeypatch,
        max_retries=1,
        retry_backoff_seconds=0.25,
    )
    unavailable = _response(error=_HTTPError(502, "gateway warming"))
    success = _response(
        lines=[
            'data: {"choices":[{"delta":{"content":"ready"}}]}',
            "data: [DONE]",
        ]
    )
    post = Mock(side_effect=[unavailable, success])
    sleep = Mock()
    monkeypatch.setattr(llm_module.requests, "post", post)
    monkeypatch.setattr(llm_module.time, "sleep", sleep)

    events = list(agent.stream_task({"prompt": "hello"}))

    final = events[-1]["result"]
    assert final["status"] == "success"
    assert final["raw_output"] == "ready"
    assert final["exo_request"]["attempt_count"] == 2
    assert [call.args[0] for call in post.call_args_list] == [
        "http://exo.test:52415/v1/chat/completions",
        "http://exo.test:52415/v1/chat/completions",
    ]
    request_ids = [
        call.kwargs["headers"]["X-Request-ID"] for call in post.call_args_list
    ]
    assert len(set(request_ids)) == 1
    sleep.assert_called_once_with(0.25)


def test_streaming_read_timeout_is_not_replayed_or_learned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        monkeypatch,
        max_retries=3,
        retry_backoff_seconds=0,
    )
    response = _response()
    response.iter_lines.side_effect = ReadTimeout("read timed out")
    post = Mock(return_value=response)
    monkeypatch.setattr(llm_module.requests, "post", post)

    events = list(agent.stream_task({"prompt": "hello"}))

    final = events[-1]["result"]
    assert final["status"] == "failed"
    assert final["provider"] == "exo"
    assert final["fallback_used"] is False
    assert final["outcome_class"] == "provider_failure"
    assert final["learning_eligible"] is False
    assert final["failure_kind"] == "read_timeout"
    assert final["attempt_count"] == 1
    post.assert_called_once()


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

    assert [event["type"] for event in events] == ["final"]
    result = events[-1]["result"]
    assert result["status"] == "failed"
    assert result["provider"] == "exo"
    assert result["fallback_used"] is False
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
    headers = post.call_args.kwargs["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"
    assert headers["Authorization"] == "Bearer api-key"
    assert headers["X-Artemis-Agent"] == "LLM Agent"
    assert headers["X-Request-ID"]
    response.close.assert_called_once_with()


def test_empty_successful_stream_uses_failed_final_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    response = _response(lines=[])
    monkeypatch.setattr(llm_module.requests, "post", Mock(return_value=response))

    events = list(agent.stream_task({"prompt": "hello"}))

    assert [event["type"] for event in events] == ["final"]
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
    assert len(events) == 2
    assert events[-1]["type"] == "final"
    assert events[-1]["result"]["status"] == "failed"
    assert events[-1]["result"]["llm_error"] == "connection dropped"


def test_partial_stream_connection_failure_is_not_safe_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        monkeypatch,
        max_retries=3,
        retry_backoff_seconds=0,
    )
    response = _response()

    def partial_lines(**_kwargs: object):
        yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
        raise ConnectionError("connection refused after response started")

    response.iter_lines.side_effect = partial_lines
    post = Mock(return_value=response)
    monkeypatch.setattr(llm_module.requests, "post", post)

    events = list(agent.stream_task({"prompt": "hello"}))

    assert events[0] == {"type": "token", "text": "partial"}
    final = events[-1]["result"]
    assert final["status"] == "failed"
    assert final["failure_kind"] == "connect_timeout"
    assert final["retryable"] is False
    assert final["attempt_count"] == 1
    post.assert_called_once()


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
