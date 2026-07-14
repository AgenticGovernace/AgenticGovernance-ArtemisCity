"""Tests for the LLM agent (src/agents/llm_agent.py)."""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.agents.llm_agent import DEFAULT_EXO_MODEL_ID, LLMAgent


def _http_error(status_code: int, message: str = "endpoint failed") -> Exception:
    exc = Exception(message)
    exc.response = Mock(status_code=status_code)  # type: ignore[attr-defined]
    return exc


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

        with patch(
            "src.agents.llm_agent.requests.post", return_value=mocked_response
        ) as post:
            result = agent.perform_task({"prompt": "hello"})

        assert agent.base_url == "http://localhost:52415/v1"
        assert result["status"] == "success"
        assert result["summary"] == "hello from exo"
        assert result["provider"] == "exo"
        assert result["model"] == "test-model"
        assert result["model_url"] == "http://localhost:52415/v1"
        assert post.call_args.args[0] == "http://localhost:52415/v1/chat/completions"

    def test_perform_task_appends_v1_to_task_model_url(self):
        """A task-level model URL is exposed as a /v1 API base."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {
            "id": "resp_2",
            "choices": [{"message": {"content": "custom endpoint response"}}],
        }

        with patch(
            "src.agents.llm_agent.requests.post", return_value=mocked_response
        ) as post:
            result = agent.perform_task(
                {
                    "prompt": "hello",
                    "model_url": "http://localhost:52415/models/test-model",
                }
            )

        assert result["status"] == "success"
        assert result["summary"] == "custom endpoint response"
        assert result["model_url"] == "http://localhost:52415/models/test-model/v1"
        assert (
            post.call_args.args[0]
            == "http://localhost:52415/models/test-model/v1/chat/completions"
        )

    def test_perform_task_trims_chat_completions_suffix_from_public_url(self):
        """A pre-suffixed chat endpoint should be exposed as its /v1 API base."""
        agent = LLMAgent(
            model_url="http://localhost:52415/v1/chat/completions",
            model_id="test-model",
        )
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "already suffixed"}}],
        }

        with patch(
            "src.agents.llm_agent.requests.post", return_value=mocked_response
        ) as post:
            result = agent.perform_task({"prompt": "hello"})

        assert result["status"] == "success"
        assert result["model_url"] == "http://localhost:52415/v1"
        assert post.call_args.args[0] == "http://localhost:52415/v1/chat/completions"

    def test_perform_task_keeps_v1_only_url_as_public_url(self):
        """A URL ending in /v1 remains the public URL."""
        agent = LLMAgent(
            model_url="http://localhost:52415/v1",
            model_id="test-model",
        )
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "v1 promoted"}}],
        }
        with patch(
            "src.agents.llm_agent.requests.post", return_value=mocked_response
        ) as post:
            result = agent.perform_task({"prompt": "hello"})
        assert result["model_url"] == "http://localhost:52415/v1"
        assert post.call_args.args[0] == "http://localhost:52415/v1/chat/completions"

    def test_perform_task_trims_any_path_after_v1_from_public_url(self):
        """A URL under /v1 is exposed as the /v1 API base link."""
        agent = LLMAgent(
            model_url="http://localhost:52415/v1/models",
            model_id="test-model",
        )
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {
            "choices": [{"message": {"content": "trimmed"}}],
        }

        with patch(
            "src.agents.llm_agent.requests.post", return_value=mocked_response
        ) as post:
            result = agent.perform_task({"prompt": "hello"})

        assert result["model_url"] == "http://localhost:52415/v1"
        assert post.call_args.args[0] == "http://localhost:52415/v1/chat/completions"

    def test_perform_task_falls_back_to_responses_endpoint(self):
        """A chat endpoint miss should retry Exo's supported Responses API."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")
        missing_endpoint = Mock()
        missing_endpoint.raise_for_status.side_effect = _http_error(404, "not found")
        responses_response = Mock()
        responses_response.raise_for_status.return_value = None
        responses_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello from responses"}
                    ],
                }
            ],
        }

        with patch(
            "src.agents.llm_agent.requests.post",
            side_effect=[missing_endpoint, responses_response],
        ) as post:
            result = agent.perform_task({"prompt": "hello"})

        assert result["status"] == "success"
        assert result["summary"] == "hello from responses"
        assert result["model_url"] == "http://localhost:52415/v1"
        assert post.call_args_list[0].args[0] == (
            "http://localhost:52415/v1/chat/completions"
        )
        assert post.call_args_list[1].args[0] == "http://localhost:52415/v1/responses"
        assert post.call_args_list[1].kwargs["json"]["input"] == [
            {"role": "user", "content": "hello"}
        ]

    def test_perform_task_blank_model_auto_detects_running_exo_model(self):
        """Blank EXO_MODEL_ID should use a model already loaded in Exo."""
        running_models = Mock()
        running_models.raise_for_status.return_value = None
        running_models.json.return_value = {
            "models": [{"model": "mlx-community/running-model"}]
        }
        completion = Mock()
        completion.raise_for_status.return_value = None
        completion.json.return_value = {
            "choices": [{"message": {"content": "running model response"}}]
        }

        with patch.dict("os.environ", {"EXO_MODEL_ID": ""}):
            agent = LLMAgent(base_url="http://localhost:52415")
        with (
            patch("src.agents.llm_agent.requests.get", return_value=running_models),
            patch(
                "src.agents.llm_agent.requests.post", return_value=completion
            ) as post,
        ):
            result = agent.perform_task({"prompt": "hello"})

        assert result["status"] == "success"
        assert result["model"] == "mlx-community/running-model"
        assert post.call_args.kwargs["json"]["model"] == ("mlx-community/running-model")

    def test_perform_task_blank_model_uses_non_empty_default_when_none_running(self):
        """No loaded model should use the valid lightweight Exo default."""
        running_models = Mock()
        running_models.raise_for_status.return_value = None
        running_models.json.return_value = {"models": []}
        completion = Mock()
        completion.raise_for_status.return_value = None
        completion.json.return_value = {
            "choices": [{"message": {"content": "default model response"}}]
        }

        with patch.dict("os.environ", {"EXO_MODEL_ID": ""}):
            agent = LLMAgent(base_url="http://localhost:52415")
        with (
            patch("src.agents.llm_agent.requests.get", return_value=running_models),
            patch(
                "src.agents.llm_agent.requests.post", return_value=completion
            ) as post,
        ):
            result = agent.perform_task({"prompt": "hello"})

        assert result["model"] == DEFAULT_EXO_MODEL_ID
        assert post.call_args.kwargs["json"]["model"] == DEFAULT_EXO_MODEL_ID
        assert post.call_args.kwargs["json"]["model"] != ""

    def test_perform_task_fallback_when_endpoint_unavailable(self):
        """An unavailable Exo call must fail rather than claim LLM success."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")

        with patch(
            "src.agents.llm_agent.requests.post",
            side_effect=RuntimeError("connection failed"),
        ):
            result = agent.perform_task({"prompt": "test prompt"})

        assert result["status"] == "failed"
        assert result["provider"] == "fallback"
        assert "LLM execution unavailable" in result["summary"]
        assert "test-model" in result["summary"]

    def test_perform_task_requires_prompt_or_messages(self):
        """An empty payload should fail fast with a clear message."""
        agent = LLMAgent()
        result = agent.perform_task({})
        assert result["status"] == "failed"
        assert "No prompt or messages provided" in result["summary"]

    # --- Streaming ----------------------------------------------------

    def test_stream_task_yields_tokens_then_final(self):
        """A streaming Exo response yields token events then exactly one final."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")

        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":", "}}]}',
            'data: {"choices":[{"delta":{"content":"world!"}}]}',
            "data: [DONE]",
        ]
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.iter_lines.return_value = iter(sse_lines)
        mocked_response.close.return_value = None

        with patch(
            "src.agents.llm_agent.requests.post", return_value=mocked_response
        ) as post:
            events = list(agent.stream_task({"prompt": "hi"}))

        tokens = [e["text"] for e in events if e["type"] == "token"]
        finals = [e for e in events if e["type"] == "final"]
        assert tokens == ["Hello", ", ", "world!"]
        assert len(finals) == 1
        assert finals[0]["result"]["status"] == "success"
        assert finals[0]["result"]["summary"] == "Hello, world!"
        assert finals[0]["result"]["provider"] == "exo"
        assert finals[0]["result"]["model_url"] == "http://localhost:52415/v1"
        assert post.call_args.args[0] == "http://localhost:52415/v1/chat/completions"

    def test_stream_task_falls_back_when_exo_errors(self):
        """When Exo raises mid-stream, a fallback token + final event are emitted."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")
        with patch(
            "src.agents.llm_agent.requests.post",
            side_effect=RuntimeError("conn refused"),
        ):
            events = list(agent.stream_task({"prompt": "hi there"}))

        tokens = [e["text"] for e in events if e["type"] == "token"]
        finals = [e for e in events if e["type"] == "final"]
        assert len(finals) == 1
        assert finals[0]["result"]["provider"] == "fallback"
        assert finals[0]["result"]["status"] == "failed"
        assert "LLM execution unavailable" in finals[0]["result"]["summary"]
        # Single fallback token so the UI animation still renders.
        assert len(tokens) == 1
        assert tokens[0] == finals[0]["result"]["summary"]

    def test_stream_task_empty_payload_fails_fast(self):
        """No prompt -> single final event with failed status, no tokens."""
        agent = LLMAgent()
        events = list(agent.stream_task({}))
        assert events == [
            {
                "type": "final",
                "result": {
                    "status": "failed",
                    "summary": "No prompt or messages provided for LLM processing.",
                },
            }
        ]

    def test_stream_task_skips_unparseable_sse_lines(self):
        """Malformed lines or non-data: prefixes are ignored, not raised."""
        agent = LLMAgent(base_url="http://localhost:52415", model_id="test-model")
        sse_lines = [
            ": keep-alive",
            "event: ping",
            "data: not-json",
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            "data: [DONE]",
        ]
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.iter_lines.return_value = iter(sse_lines)

        with patch("src.agents.llm_agent.requests.post", return_value=mocked_response):
            events = list(agent.stream_task({"prompt": "x"}))
        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert tokens == ["ok"]
