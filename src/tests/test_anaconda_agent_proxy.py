"""Tests for src/integration/anaconda_agent_proxy.py + anaconda_stack.py."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.integration.anaconda_agent_proxy import (ANACONDA_API_KEY_ENV,
                                                  ARTEMIS_PROVIDER_TAG,
                                                  DEFAULT_ANACONDA_API_KEY,
                                                  AnacondaAgentProxy,
                                                  discover_anaconda_agents,
                                                  parse_port_map,
                                                  parse_sse_chat_completion)
from src.integration.anaconda_stack import (DEFAULT_CAPABILITIES,
                                            register_anaconda_stack)

# ---------------------------------------------------------------------------
# parse_port_map
# ---------------------------------------------------------------------------


class TestParsePortMap:
    def test_empty(self):
        assert parse_port_map("") == {}
        assert parse_port_map(None) == {}

    def test_single(self):
        assert parse_port_map("artemis-oracle:50053") == {"artemis-oracle": 50053}

    def test_multiple_with_whitespace(self):
        env = " artemis-oracle:50053 , artemis-loki:50054,artemis-compsuite:50055 "
        assert parse_port_map(env) == {
            "artemis-oracle": 50053,
            "artemis-loki": 50054,
            "artemis-compsuite": 50055,
        }

    def test_skips_malformed_entries(self):
        env = "artemis-oracle:50053,nocolon,empty:,name:notaport,artemis-loki:50054"
        assert parse_port_map(env) == {
            "artemis-oracle": 50053,
            "artemis-loki": 50054,
        }


# ---------------------------------------------------------------------------
# parse_sse_chat_completion
# ---------------------------------------------------------------------------


def _sse(*chunks: Dict[str, Any]) -> List[bytes]:
    """Build a list of SSE-formatted bytes lines from chunk dicts.

    Mirrors what requests.Response.iter_lines() returns: one byte string
    per line, with blank lines between data: lines stripped out.
    """
    out: List[bytes] = []
    for chunk in chunks:
        out.append(f"data: {json.dumps(chunk)}".encode("utf-8"))
    out.append(b"data: [DONE]")
    return out


def _chunk(
    content=None,
    reasoning=None,
    finish=None,
    usage=None,
    model="artemis-oracle",
    id_="cmpl-test",
):
    delta: Dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    body: Dict[str, Any] = {
        "id": id_,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


class TestParseSSEChatCompletion:
    def test_assembles_content_only(self):
        stream = _sse(
            _chunk(content="Hello"),
            _chunk(content=", "),
            _chunk(content="world"),
            _chunk(finish="stop", usage={"total_tokens": 12}),
        )
        out = parse_sse_chat_completion(stream)
        assert out["content"] == "Hello, world"
        assert out["reasoning"] == ""
        assert out["usage"] == {"total_tokens": 12}
        assert out["model"] == "artemis-oracle"
        assert out["finish_reason"] == "stop"
        assert out["id"] == "cmpl-test"

    def test_separates_reasoning_from_content(self):
        stream = _sse(
            _chunk(reasoning="The user said hi. "),
            _chunk(reasoning="I should respond warmly."),
            _chunk(content="Hello!"),
            _chunk(finish="stop", usage={"prompt_tokens": 3, "completion_tokens": 1}),
        )
        out = parse_sse_chat_completion(stream)
        assert out["content"] == "Hello!"
        assert out["reasoning"] == "The user said hi. I should respond warmly."
        assert out["finish_reason"] == "stop"

    def test_ignores_garbage_lines(self):
        stream = [
            b": comment line",
            b"data: {not valid json",
            b"data: " + json.dumps(_chunk(content="ok")).encode(),
            b"",
            b"unrelated text",
            b"data: [DONE]",
            b"data: "
            + json.dumps(_chunk(content="after done — should not be added")).encode(),
        ]
        out = parse_sse_chat_completion(stream)
        assert out["content"] == "ok"

    def test_handles_str_lines(self):
        stream = [
            f"data: {json.dumps(_chunk(content='abc'))}",
            "data: [DONE]",
        ]
        out = parse_sse_chat_completion(stream)
        assert out["content"] == "abc"

    def test_empty_stream(self):
        out = parse_sse_chat_completion([])
        assert out["content"] == ""
        assert out["reasoning"] == ""
        assert out["usage"] == {}
        assert out["finish_reason"] is None


# ---------------------------------------------------------------------------
# AnacondaAgentProxy
# ---------------------------------------------------------------------------


class TestAnacondaAgentProxy:
    def test_constructor_sets_endpoint(self):
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        assert p.name == "artemis-oracle"
        assert p.port == 50053
        assert p.chat_endpoint == "http://127.0.0.1:50053/v1/chat/completions"
        assert p.capabilities == ["llm_chat"]
        assert p.model == "artemis-oracle"

    def test_constructor_accepts_capabilities_and_model(self):
        p = AnacondaAgentProxy(
            name="artemis-loki",
            port=50054,
            capabilities=["code_write", "git"],
            model="loki-override",
        )
        assert p.capabilities == ["code_write", "git"]
        assert p.model == "loki-override"

    def test_build_messages_prompt_only(self):
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        msgs = p._build_messages({"prompt": "ping"})
        assert msgs == [{"role": "user", "content": "ping"}]

    def test_build_messages_with_system_and_history(self):
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        msgs = p._build_messages(
            {
                "system_prompt": "You are Oracle.",
                "history": [
                    {"role": "user", "content": "earlier turn"},
                    {"role": "assistant", "content": "earlier reply"},
                    {
                        "role": "user",
                        "content": "skip me — incomplete",
                        "content2": "noise",
                    },
                    {"not": "a role"},  # malformed entry, dropped
                ],
                "prompt": "now this",
            }
        )
        assert msgs[0] == {"role": "system", "content": "You are Oracle."}
        # All four history entries had content; only the malformed last one (no
        # role key) should drop.
        assert msgs[-1] == {"role": "user", "content": "now this"}
        assert {"role": "user", "content": "earlier turn"} in msgs
        assert {"role": "assistant", "content": "earlier reply"} in msgs

    def test_build_messages_falls_back_to_instruction_then_content(self):
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        assert p._build_messages({"instruction": "do x"})[-1]["content"] == "do x"
        assert p._build_messages({"content": "raw"})[-1]["content"] == "raw"

    def test_perform_task_returns_error_when_empty(self):
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        result = p.perform_task({})
        assert result["error"] == "no prompt provided"
        assert result["content"] == ""

    def test_perform_task_posts_and_parses_sse(self):
        p = AnacondaAgentProxy(
            name="artemis-oracle",
            port=50053,
            capabilities=["orchestration"],
            timeout=5,
        )
        sse_lines = _sse(
            _chunk(reasoning="The user wants a ping. "),
            _chunk(reasoning="I'll keep it short."),
            _chunk(content="pong"),
            _chunk(
                finish="stop",
                usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            ),
        )
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda self_: self_
        mock_resp.__exit__ = lambda *a, **k: None
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(sse_lines)
        with patch(
            "src.integration.anaconda_agent_proxy.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            out = p.perform_task(
                {
                    "prompt": "ping",
                    "system_prompt": "Be brief.",
                    "temperature": 0.2,
                    "max_tokens": 8,
                }
            )

        # Inspect outgoing request
        assert mock_post.call_count == 1
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "artemis-oracle"
        assert call_kwargs["json"]["temperature"] == 0.2
        assert call_kwargs["json"]["max_tokens"] == 8
        assert call_kwargs["json"]["messages"] == [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "ping"},
        ]
        assert call_kwargs["stream"] is True
        # And the parsed result
        assert out["content"] == "pong"
        assert out["reasoning"] == "The user wants a ping. I'll keep it short."
        assert out["usage"]["total_tokens"] == 3
        assert out["finish_reason"] == "stop"
        assert out["agent"] == "artemis-oracle"
        assert out["port"] == 50053
        assert out["provider"] == "anaconda_agent_studio"
        assert out["summary"] == "pong"

    def test_perform_task_swallows_request_errors(self):
        import requests as _requests

        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        with patch(
            "src.integration.anaconda_agent_proxy.requests.post",
            side_effect=_requests.ConnectionError("refused"),
        ):
            out = p.perform_task({"prompt": "ping"})
        assert out["content"] == ""
        assert "unreachable" in out["summary"].lower()
        assert "unreachable" in out["error"]
        assert out["agent"] == "artemis-oracle"

    def test_default_api_key_is_permissive(self, monkeypatch):
        monkeypatch.delenv(ANACONDA_API_KEY_ENV, raising=False)
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        assert p.api_key == DEFAULT_ANACONDA_API_KEY == "*"

    def test_api_key_picked_up_from_env(self, monkeypatch):
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-from-env")
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        assert p.api_key == "sk-from-env"

    def test_explicit_api_key_overrides_env(self, monkeypatch):
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-from-env")
        p = AnacondaAgentProxy(
            name="artemis-oracle",
            port=50053,
            api_key="sk-explicit",
        )
        assert p.api_key == "sk-explicit"

    def test_empty_env_falls_back_to_default(self, monkeypatch):
        # An unset-but-blank env var must NOT result in an empty bearer --
        # some Anaconda builds 401 on `Authorization: Bearer ` (trailing
        # space).  Empty string falls through to the permissive default.
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "")
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        assert p.api_key == DEFAULT_ANACONDA_API_KEY

    def test_perform_task_sends_bearer_authorization(self, monkeypatch):
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-test")
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        sse_lines = _sse(_chunk(content="ok"), _chunk(finish="stop"))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda self_: self_
        mock_resp.__exit__ = lambda *a, **k: None
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(sse_lines)
        with patch(
            "src.integration.anaconda_agent_proxy.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            p.perform_task({"prompt": "ping"})
        sent_headers = mock_post.call_args.kwargs["headers"]
        assert sent_headers["Authorization"] == "Bearer sk-test"
        assert sent_headers["Accept"] == "text/event-stream"
        assert sent_headers["Content-Type"] == "application/json"

    def test_perform_task_default_bearer_when_env_unset(self, monkeypatch):
        monkeypatch.delenv(ANACONDA_API_KEY_ENV, raising=False)
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        sse_lines = _sse(_chunk(content="ok"), _chunk(finish="stop"))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda self_: self_
        mock_resp.__exit__ = lambda *a, **k: None
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(sse_lines)
        with patch(
            "src.integration.anaconda_agent_proxy.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            p.perform_task({"prompt": "ping"})
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer *"

    def test_summary_truncates_long_content(self):
        p = AnacondaAgentProxy(name="artemis-oracle", port=50053)
        long_content = "x" * 500
        sse_lines = _sse(
            _chunk(content=long_content),
            _chunk(finish="stop"),
        )
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda self_: self_
        mock_resp.__exit__ = lambda *a, **k: None
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(sse_lines)
        with patch(
            "src.integration.anaconda_agent_proxy.requests.post",
            return_value=mock_resp,
        ):
            out = p.perform_task({"prompt": "go"})
        assert out["content"] == long_content
        assert len(out["summary"]) == 280
        assert out["summary"].endswith("...")


# ---------------------------------------------------------------------------
# discover_anaconda_agents
# ---------------------------------------------------------------------------


class TestDiscoverAnacondaAgents:
    def _models_response(self):
        return {
            "object": "list",
            "data": [
                {
                    "id": "Anaconda Assistant",
                    "object": "model",
                    "meta": {"agent_id": "anaconda-assistant", "provider": "anaconda"},
                },
                {
                    "id": "artemis-oracle",
                    "object": "model",
                    "meta": {
                        "agent_id": "artemis-oracle",
                        "provider": ARTEMIS_PROVIDER_TAG,
                        "description": "Coordinator.",
                    },
                },
                {
                    "id": "artemis-loki",
                    "object": "model",
                    "meta": {
                        "agent_id": "artemis-loki",
                        "provider": ARTEMIS_PROVIDER_TAG,
                        "description": "Writer.",
                    },
                },
            ],
        }

    def test_filters_to_artemiscity_provider(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = self._models_response()
        with patch(
            "src.integration.anaconda_agent_proxy.requests.get",
            return_value=mock_resp,
        ):
            agents = discover_anaconda_agents()
        ids = {a["id"] for a in agents}
        assert ids == {"artemis-oracle", "artemis-loki"}

    def test_returns_empty_on_connection_error(self):
        import requests as _requests

        with patch(
            "src.integration.anaconda_agent_proxy.requests.get",
            side_effect=_requests.ConnectionError("nope"),
        ):
            assert discover_anaconda_agents() == []

    def test_discovery_sends_bearer_authorization(self, monkeypatch):
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-disc")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"object": "list", "data": []}
        with patch(
            "src.integration.anaconda_agent_proxy.requests.get",
            return_value=mock_resp,
        ) as mock_get:
            discover_anaconda_agents()
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-disc"

    def test_discovery_default_bearer_when_env_unset(self, monkeypatch):
        monkeypatch.delenv(ANACONDA_API_KEY_ENV, raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"object": "list", "data": []}
        with patch(
            "src.integration.anaconda_agent_proxy.requests.get",
            return_value=mock_resp,
        ) as mock_get:
            discover_anaconda_agents()
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer *"

    def test_handles_malformed_body(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": "not a list"}
        with patch(
            "src.integration.anaconda_agent_proxy.requests.get",
            return_value=mock_resp,
        ):
            assert discover_anaconda_agents() == []


# ---------------------------------------------------------------------------
# register_anaconda_stack
# ---------------------------------------------------------------------------


class _StubRegistry:
    def __init__(self):
        self.agents: List[AnacondaAgentProxy] = []

    def register_agent(self, agent):
        self.agents.append(agent)


class TestRegisterAnacondaStack:
    def test_no_op_when_port_map_unset(self, monkeypatch):
        monkeypatch.delenv("ANACONDA_AGENT_PORTS", raising=False)
        reg = _StubRegistry()
        assert register_anaconda_stack(reg) == []
        assert reg.agents == []

    def test_skip_discovery_registers_all_port_mapped(self, monkeypatch):
        monkeypatch.setenv(
            "ANACONDA_AGENT_PORTS", "artemis-oracle:50053,artemis-loki:50054"
        )
        reg = _StubRegistry()
        registered = register_anaconda_stack(reg, skip_discovery=True)
        assert set(registered) == {"artemis-oracle", "artemis-loki"}
        assert {a.name for a in reg.agents} == {"artemis-oracle", "artemis-loki"}
        oracle = next(a for a in reg.agents if a.name == "artemis-oracle")
        assert oracle.capabilities == DEFAULT_CAPABILITIES["artemis-oracle"]
        assert oracle.port == 50053

    def test_filters_to_discovered_agents(self, monkeypatch):
        monkeypatch.setenv(
            "ANACONDA_AGENT_PORTS",
            "artemis-oracle:50053,artemis-loki:50054,artemis-compsuite:50055",
        )
        reg = _StubRegistry()
        # Discovery only reports oracle and loki — compsuite is stopped.
        with patch(
            "src.integration.anaconda_stack.discover_anaconda_agents",
            return_value=[
                {"id": "artemis-oracle", "meta": {}},
                {"id": "artemis-loki", "meta": {}},
            ],
        ):
            registered = register_anaconda_stack(reg)
        assert set(registered) == {"artemis-oracle", "artemis-loki"}
        assert "artemis-compsuite" not in {a.name for a in reg.agents}

    def test_capability_overrides(self, monkeypatch):
        monkeypatch.setenv("ANACONDA_AGENT_PORTS", "artemis-loki:50054")
        reg = _StubRegistry()
        registered = register_anaconda_stack(
            reg,
            capability_overrides={"artemis-loki": ["sandboxed_read_only"]},
            skip_discovery=True,
        )
        assert registered == ["artemis-loki"]
        assert reg.agents[0].capabilities == ["sandboxed_read_only"]

    def test_returns_empty_when_desktop_silent(self, monkeypatch):
        monkeypatch.setenv("ANACONDA_AGENT_PORTS", "artemis-oracle:50053")
        reg = _StubRegistry()
        with patch(
            "src.integration.anaconda_stack.discover_anaconda_agents",
            return_value=[],
        ):
            assert register_anaconda_stack(reg) == []
        assert reg.agents == []

    def test_api_key_plumbed_from_env_to_proxy(self, monkeypatch):
        monkeypatch.setenv("ANACONDA_AGENT_PORTS", "artemis-oracle:50053")
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-stack")
        reg = _StubRegistry()
        register_anaconda_stack(reg, skip_discovery=True)
        assert reg.agents[0].api_key == "sk-stack"

    def test_explicit_api_key_overrides_env_in_stack(self, monkeypatch):
        monkeypatch.setenv("ANACONDA_AGENT_PORTS", "artemis-oracle:50053")
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-env")
        reg = _StubRegistry()
        register_anaconda_stack(reg, skip_discovery=True, api_key="sk-explicit")
        assert reg.agents[0].api_key == "sk-explicit"

    def test_api_key_passed_to_discovery(self, monkeypatch):
        monkeypatch.setenv("ANACONDA_AGENT_PORTS", "artemis-oracle:50053")
        monkeypatch.setenv(ANACONDA_API_KEY_ENV, "sk-stack")
        reg = _StubRegistry()
        with patch(
            "src.integration.anaconda_stack.discover_anaconda_agents",
            return_value=[{"id": "artemis-oracle", "meta": {}}],
        ) as mock_disc:
            register_anaconda_stack(reg)
        assert mock_disc.call_args.kwargs["api_key"] == "sk-stack"
