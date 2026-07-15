"""Focused tests for real Exo calls exposed through the JSON bridge."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import src.api_bridge as bridge
from src.api_bridge import BridgeError, dispatch
from src.integration.sandbox import ToolPolicy


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Install an LLMAgent double that records its governed task context."""

    class FakeLLMAgent:
        name = "LLM Agent"
        capabilities = ["llm_chat", "text_generation"]
        model_id = "configured-model"
        model_url = "http://exo.test:52415/v1"
        api_key = "never-return-this-secret"
        result: dict[str, Any] = {
            "status": "success",
            "summary": "real model output",
            "raw_output": "real model output",
            "provider": "exo",
            "model": "configured-model",
            "error": None,
            "exo_request": {
                "request_id": "req-1",
                "http_status": 200,
                "endpoint": "http://exo.test:52415/v1/chat/completions",
            },
        }
        last_context: dict[str, Any] | None = None
        allow_action = True

        def get_sandbox_policies(self) -> list[ToolPolicy]:
            if not self.allow_action:
                return []
            return [
                ToolPolicy(
                    name="exo_http",
                    paths=["http://exo.test:52415/**"],
                    operations=["chat"],
                )
            ]

        def get_sandbox_actions(self, _context: dict) -> list[dict]:
            return [
                {
                    "tool_name": "exo_http",
                    "path": self.model_url,
                    "operation": "chat",
                }
            ]

        def perform_task(self, context: dict) -> dict:
            type(self).last_context = context
            return dict(type(self).result)

    monkeypatch.setattr(bridge, "LLMAgent", FakeLLMAgent)
    return FakeLLMAgent


def test_llm_chat_uses_authoritative_agent_and_preserves_evidence(fake_llm) -> None:
    """Chat input reaches LLMAgent and its real provider evidence is unchanged."""
    result = dispatch(
        "llm.chat",
        {
            "messages": [{"role": "user", "content": "Hello Exo"}],
            "model": "chosen-model",
            "options": {
                "temperature": 0.4,
                "maxTokens": 256,
                "systemPrompt": "Be concise",
            },
        },
    )

    assert fake_llm.last_context == {
        "temperature": 0.4,
        "max_tokens": 256,
        "model": "chosen-model",
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hello Exo"},
        ],
    }
    assert result["status"] == "success"
    assert result["summary"] == "real model output"
    assert result["raw"] == "real model output"
    assert result["provider"] == "exo"
    assert result["model"] == "configured-model"
    assert result["error"] is None
    assert result["exo_request"]["request_id"] == "req-1"


def test_llm_complete_builds_prompt_context(fake_llm) -> None:
    """Text completion uses the same real agent path with normalized options."""
    result = dispatch(
        "llm.complete",
        {
            "prompt": "Finish this sentence",
            "options": {"temperature": 0, "max_tokens": 32},
        },
    )

    assert fake_llm.last_context == {
        "temperature": 0.0,
        "max_tokens": 32,
        "prompt": "Finish this sentence",
    }
    assert result["raw"] == result["summary"]


@pytest.mark.parametrize(
    ("failure_kind", "upstream_status", "expected_code"),
    [
        ("rate_limited", 429, "RATE_LIMITED"),
        ("read_timeout", None, "TIMEOUT"),
        ("connect_timeout", None, "SERVICE_UNAVAILABLE"),
        ("http_error", 503, "SERVICE_UNAVAILABLE"),
        ("invalid_response", 200, "PROVIDER_ERROR"),
    ],
)
def test_llm_provider_failures_remain_structured(
    fake_llm,
    failure_kind: str,
    upstream_status: int | None,
    expected_code: str,
) -> None:
    """Provider failures remain data, with a stable code for HTTP mapping."""
    fake_llm.result = {
        "status": "failed",
        "summary": "Exo is unavailable",
        "provider": "exo",
        "fallback_used": False,
        "model": "configured-model",
        "error": "Exo is unavailable",
        "llm_error": "redacted transport detail",
        "failure_kind": failure_kind,
        "upstream_status_code": upstream_status,
        "exo_request": {
            "request_id": "req-failed",
            "http_status": upstream_status,
            "failure_kind": failure_kind,
        },
    }

    result = dispatch(
        "llm.chat",
        {"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert result["status"] == "failed"
    assert result["summary"] == "Exo is unavailable"
    assert result["error"] == "Exo is unavailable"
    assert result["raw"] is None
    assert result["exo_request"]["request_id"] == "req-failed"
    assert result["bridge_code"] == expected_code


@pytest.mark.parametrize(
    ("command", "payload", "message"),
    [
        ("llm.chat", {}, "missing required field: messages"),
        ("llm.chat", {"messages": []}, "messages must be a non-empty array"),
        (
            "llm.chat",
            {"messages": [{"role": "tool", "content": "no"}]},
            "role must be one of",
        ),
        (
            "llm.chat",
            {"messages": [{"role": "user", "content": ""}]},
            "content must be a non-empty string",
        ),
        (
            "llm.chat",
            {
                "messages": [{"role": "user", "content": "hello"}],
                "options": {"topP": 0.9},
            },
            "unsupported LLM option",
        ),
        (
            "llm.chat",
            {
                "messages": [{"role": "user", "content": "hello"}],
                "options": {"temperature": True},
            },
            "temperature must be a number",
        ),
        (
            "llm.complete",
            {"prompt": "hello", "options": {"maxTokens": 1.5}},
            "maxTokens must be an integer",
        ),
        ("llm.complete", {"prompt": ""}, "missing required field: prompt"),
        ("llm.complete", {"prompt": "   "}, "missing required field: prompt"),
    ],
)
def test_llm_commands_reject_invalid_payloads(
    fake_llm, command: str, payload: dict, message: str
) -> None:
    """Invalid public inputs fail before LLMAgent performs a provider call."""
    with pytest.raises(BridgeError, match=message) as exc_info:
        dispatch(command, payload)
    assert exc_info.value.code == "INVALID_REQUEST"
    assert fake_llm.last_context is None


def test_llm_bridge_runs_sandbox_preflight(fake_llm) -> None:
    """A disallowed Exo action is denied before the agent is invoked."""
    fake_llm.allow_action = False

    with pytest.raises(BridgeError, match="not in whitelist") as exc_info:
        dispatch(
            "llm.chat",
            {"messages": [{"role": "user", "content": "Hello"}]},
        )

    assert exc_info.value.code == "FORBIDDEN"
    assert fake_llm.last_context is None


def test_llm_config_is_environment_backed_and_redacts_secret(fake_llm) -> None:
    """Discovery endpoints report configured Exo state without leaking keys."""
    result = dispatch("llm.config")

    assert result["source"] == "configured"
    assert result["default_model"] == "configured-model"
    assert result["models"][0]["running"] is None
    assert result["providers"][0] == {
        "id": "exo",
        "name": "Exo",
        "enabled": True,
        "base_url": "http://exo.test:52415/v1",
        "api_key_configured": True,
        "source": "environment",
    }
    assert "never-return-this-secret" not in json.dumps(result)


def test_llm_chat_cli_envelope_round_trip(
    fake_llm, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stdin/stdout bridge envelope exposes the new command contract."""
    request = {
        "command": "llm.chat",
        "payload": {"messages": [{"role": "user", "content": "Hello"}]},
    }
    stdout = io.StringIO()
    monkeypatch.setattr(bridge.sys, "stdin", io.StringIO(json.dumps(request)))
    monkeypatch.setattr(bridge.sys, "stdout", stdout)

    assert bridge.main([]) == 0
    envelope = json.loads(stdout.getvalue())
    assert envelope["ok"] is True
    assert envelope["data"]["provider"] == "exo"
    assert envelope["data"]["raw"] == "real model output"


def test_llm_config_subprocess_round_trip() -> None:
    """The real module entry point returns config without contacting Exo."""
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "src.api_bridge"],
        input=json.dumps({"command": "llm.config", "payload": {}}),
        text=True,
        capture_output=True,
        cwd=repo_root,
        check=False,
    )

    assert completed.returncode == 0
    envelope = json.loads(completed.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["source"] == "configured"
    assert envelope["data"]["providers"][0]["id"] == "exo"
