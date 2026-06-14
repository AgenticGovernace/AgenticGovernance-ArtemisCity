"""Forward Artemis-City agent calls to running Anaconda Agent Studio agents.

Anaconda Agent Studio (Beta as of May 2026) exposes each running agent as
an OpenAI-compatible HTTP server on a per-agent localhost port. The
project keeps a six-agent stack at ``~/Source/artemis-agent-stack/`` —
oracle, compsuite, packrat, compressor, loki, plus a model-less
validators tool server. This module bridges that running stack into the
Artemis-City :class:`AgentRegistry` so capability-based routing can
delegate work to the Anaconda agents the same way it delegates to
in-process Python agents.

Three moving parts live here:

- :func:`parse_port_map` — read ``ANACONDA_AGENT_PORTS`` into a
  ``{name: port}`` mapping.  Per-agent ports change every time Agent
  Studio restarts an agent, and Anaconda Desktop's discovery endpoint
  does not surface ports, so the mapping is supplied out-of-band via
  env.
- :func:`discover_anaconda_agents` — call Anaconda Desktop's discovery
  endpoint (port 54321, stable) and return the metadata for agents
  using the ``artemiscity`` provider tag.
- :class:`AnacondaAgentProxy` — a :class:`BaseAgent` subclass that
  forwards ``perform_task`` to one running Anaconda agent's
  ``/v1/chat/completions`` endpoint.  The agent's persona, system
  prompt, and tools live in its own ``agent.yaml``; this proxy is a
  thin HTTP transport.

Streaming caveat
----------------
Anaconda agents return Server-Sent Events even when the request body
includes ``"stream": false``, and they interleave ``reasoning_content``
chunks (the model's internal thinking) with ``content`` chunks (the
user-facing response).  The proxy consumes the SSE stream and returns
the two accumulations separately so callers can surface ``content``
while logging ``reasoning`` for audit.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import requests

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Anaconda Desktop binds its discovery endpoint to this localhost port
# regardless of which agents are running.  Override via env for non-default
# installs.
ANACONDA_DESKTOP_URL = os.getenv("ANACONDA_DESKTOP_URL", "http://127.0.0.1:54321")

# The ``provider`` tag on the agent.yaml that the stack at
# ~/Source/artemis-agent-stack/ uses to find the EXO inference server (or
# whatever local provider replaces EXO).  Used to filter discovery so the
# proxy doesn't pick up unrelated agents in the same Anaconda install.
ARTEMIS_PROVIDER_TAG = "artemiscity"

# Anaconda Agent Studio (Beta) ships with a permissive default API key of
# ``*`` -- the per-agent HTTP servers reject requests that arrive without
# any Authorization header but accept any non-empty bearer token.  Override
# via ``ANACONDA_API_KEY`` when a real key is configured in Agent Studio.
DEFAULT_ANACONDA_API_KEY = "*"
ANACONDA_API_KEY_ENV = "ANACONDA_API_KEY"


def parse_port_map(env_value: Optional[str]) -> Dict[str, int]:
    """Parse ``"name:port,name:port"`` into a ``{name: port}`` dict.

    Malformed pairs are skipped with a warning rather than raising — a
    typo in one entry should not block the whole stack from registering.
    """
    out: Dict[str, int] = {}
    if not env_value:
        return out
    for pair in env_value.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        name, port_s = pair.split(":", 1)
        name = name.strip()
        port_s = port_s.strip()
        if not name or not port_s.isdigit():
            logger.warning("Skipping malformed port pair: %r", pair)
            continue
        out[name] = int(port_s)
    return out


def discover_anaconda_agents(
    desktop_url: str = ANACONDA_DESKTOP_URL,
    provider_tag: str = ARTEMIS_PROVIDER_TAG,
    timeout: float = 5.0,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hit ``/api/agents/v1/models`` and return ``artemiscity`` agent metas.

    Returns an empty list (with a warning) when Anaconda Desktop is not
    running.  Discovery failures should never block orchestrator startup.

    Anaconda's discovery endpoint follows the same Authorization rule as
    per-agent endpoints, so we always send a bearer token: caller > env >
    permissive default (``*``).
    """
    endpoint = f"{desktop_url.rstrip('/')}/api/agents/v1/models"
    resolved = api_key if api_key is not None else os.getenv(ANACONDA_API_KEY_ENV)
    bearer = resolved if resolved else DEFAULT_ANACONDA_API_KEY
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        resp = requests.get(endpoint, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Anaconda Desktop discovery failed at %s: %s", endpoint, exc)
        return []
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    return [
        m
        for m in data
        if isinstance(m, dict)
        and isinstance(m.get("meta"), dict)
        and m["meta"].get("provider") == provider_tag
    ]


def parse_sse_chat_completion(stream: Iterable[Any]) -> Dict[str, Any]:
    """Consume an OpenAI-style SSE chat completion stream.

    Anaconda agents emit ``data: {...}`` lines (per the OpenAI streaming
    spec) and terminate with ``data: [DONE]``.  ``delta.content`` carries
    the user-facing response; ``delta.reasoning_content`` (Anaconda
    extension) carries the model's internal thinking.  The final chunk
    typically carries ``usage``.

    Args:
        stream: Anything iterable that yields ``str`` or ``bytes`` lines
            — ``requests.Response.iter_lines()`` is the common case.

    Returns:
        Dict with keys: ``content`` (assembled), ``reasoning`` (assembled),
        ``usage``, ``model``, ``id``, ``finish_reason``.
    """
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    usage: Dict[str, Any] = {}
    model = ""
    completion_id = ""
    finish_reason: Optional[str] = None

    for raw_line in stream:
        if raw_line is None:
            continue
        line = (
            raw_line.decode("utf-8")
            if isinstance(raw_line, (bytes, bytearray))
            else raw_line
        )
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON SSE payload: %r", payload[:120])
            continue
        if not completion_id and chunk.get("id"):
            completion_id = chunk["id"]
        if chunk.get("model"):
            model = chunk["model"]
        choices = chunk.get("choices") or []
        if choices:
            choice = choices[0] or {}
            delta = choice.get("delta") or {}
            content_chunk = delta.get("content")
            if isinstance(content_chunk, str):
                content_parts.append(content_chunk)
            reasoning_chunk = delta.get("reasoning_content")
            if isinstance(reasoning_chunk, str):
                reasoning_parts.append(reasoning_chunk)
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]

    return {
        "content": "".join(content_parts),
        "reasoning": "".join(reasoning_parts),
        "usage": usage,
        "model": model,
        "id": completion_id,
        "finish_reason": finish_reason,
    }


class AnacondaAgentProxy(BaseAgent):
    """Thin :class:`BaseAgent` that forwards to a running Anaconda agent.

    The Anaconda agent's persona, system prompt, document corpus, and tool
    set live in its own ``agent.yaml`` (under
    ``~/Source/artemis-agent-stack/``).  Per-agent localhost ports are
    assigned by Anaconda Desktop and change on every agent restart; the
    proxy takes the port at construction time and uses it for the lifetime
    of the registration.  Restart Artemis-City after restarting an agent.

    The proxy does not enforce the model field — Anaconda's per-agent
    runtime ignores it and routes to the embedded persona regardless.  We
    pass the agent name through anyway for log clarity.
    """

    def __init__(
        self,
        name: str,
        port: int,
        capabilities: Optional[List[str]] = None,
        host: str = "127.0.0.1",
        timeout: int = 180,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        caps = list(capabilities) if capabilities else ["llm_chat"]
        super().__init__(name=name, capabilities=caps)
        self.host = host
        self.port = int(port)
        self.base_url = f"http://{host}:{self.port}"
        self.timeout = timeout
        self.model = model or name
        # Anaconda's per-agent HTTP servers require an Authorization header.
        # Caller > env > permissive default ("*"), in that order.  We never
        # send an empty bearer -- an empty header is worse than the default
        # because some Anaconda builds 401 on it.
        resolved = api_key if api_key is not None else os.getenv(ANACONDA_API_KEY_ENV)
        self.api_key = resolved if resolved else DEFAULT_ANACONDA_API_KEY

    @property
    def chat_endpoint(self) -> str:
        """Full URL of the agent's OpenAI-compatible chat completions endpoint."""
        return f"{self.base_url}/v1/chat/completions"

    def _build_messages(self, task_context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Build an OpenAI-shape ``messages`` list from a task context.

        Accepted keys (in order of priority for the user turn):
        ``prompt`` → ``instruction`` → ``content``.  Optional
        ``system_prompt`` becomes the first message; ``history`` is a
        list of ``{role, content}`` dicts inserted between system and
        user.
        """
        messages: List[Dict[str, str]] = []
        system = task_context.get("system_prompt")
        if system:
            messages.append({"role": "system", "content": str(system)})
        history = task_context.get("history") or []
        if isinstance(history, list):
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                role = entry.get("role")
                content = entry.get("content")
                if role and content is not None:
                    messages.append({"role": str(role), "content": str(content)})
        prompt = (
            task_context.get("prompt")
            or task_context.get("instruction")
            or task_context.get("content")
            or ""
        )
        if prompt:
            messages.append({"role": "user", "content": str(prompt)})
        return messages

    def perform_task(self, task_context: Dict[str, Any]) -> Dict[str, Any]:
        """Forward the task to the Anaconda agent and return its reply.

        Returns a BaseAgent-shaped dict.  On HTTP failure, ``content`` is
        empty and ``error`` carries the requests exception message — the
        caller can decide whether to retry, route elsewhere, or surface
        the failure.  Reasoning chunks are returned separately from
        content so callers can log the model's thinking without burying
        the response.
        """
        messages = self._build_messages(task_context)
        if not messages:
            return {
                "summary": "Empty prompt",
                "content": "",
                "agent": self.name,
                "port": self.port,
                "error": "no prompt provided",
            }

        payload: Dict[str, Any] = {
            "model": task_context.get("model") or self.model,
            "messages": messages,
            "stream": False,
        }
        if "temperature" in task_context:
            payload["temperature"] = task_context["temperature"]
        if "max_tokens" in task_context:
            payload["max_tokens"] = task_context["max_tokens"]

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            with requests.post(
                self.chat_endpoint,
                json=payload,
                headers=headers,
                stream=True,
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                result = parse_sse_chat_completion(resp.iter_lines())
        except requests.RequestException as exc:
            logger.warning(
                "Anaconda agent %r at %s unreachable: %s",
                self.name,
                self.chat_endpoint,
                exc,
            )
            return {
                "summary": f"Anaconda agent {self.name} unreachable",
                "content": "",
                "agent": self.name,
                "port": self.port,
                "error": str(exc),
            }

        content = result["content"]
        # Keep summary bounded so registry-level logs don't get flooded.
        summary = content if len(content) <= 280 else content[:277] + "..."

        return {
            "summary": summary,
            "content": content,
            "reasoning": result["reasoning"] or None,
            "usage": result["usage"],
            "model": result["model"] or self.model,
            "id": result["id"],
            "finish_reason": result["finish_reason"],
            "agent": self.name,
            "port": self.port,
            "provider": "anaconda_agent_studio",
        }
