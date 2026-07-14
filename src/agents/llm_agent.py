"""LLM-backed agent implementation with Exo model endpoint calls."""

from __future__ import annotations

import json
import os
import typing
from urllib.parse import urlsplit

from src.integration.sandbox import ToolPolicy

from . import base_agent

DEFAULT_EXO_BASE_URL = "http://localhost:52415"
DEFAULT_EXO_MODEL_ID = "mlx-community/Qwen3-0.6B-4bit"


class _MissingRequests:
    """Stand in for requests when dependencies have not been installed."""

    def post(self, *_args: typing.Any, **_kwargs: typing.Any) -> typing.Any:
        raise RuntimeError(
            "The 'requests' package is not installed. Run `make install` "
            "from the repository root to enable Exo HTTP calls."
        )

    def get(self, *_args: typing.Any, **_kwargs: typing.Any) -> typing.Any:
        return self.post(*_args, **_kwargs)


requests: typing.Any
try:
    import requests as _requests
except ModuleNotFoundError:
    requests = _MissingRequests()
else:
    requests = _requests


class LLMAgent(base_agent.BaseAgent):
    """Route prompt-style tasks to the configured Exo model endpoint."""

    def __init__(
        self,
        name: str = "LLM Agent",
        base_url: typing.Optional[str] = None,
        model_url: typing.Optional[str] = None,
        model_id: typing.Optional[str] = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            name,
            capabilities=[
                "llm_chat",
                "text_generation",
                "reasoning",
                # Aliases so common generic requests route here.
                "chat",
                "general",
                "inference",
            ],
        )
        configured_url = (
            model_url
            or os.getenv("EXO_MODEL_URL")
            or base_url
            or os.getenv("EXO_BASE_URL", DEFAULT_EXO_BASE_URL)
        )
        self.model_url = self._with_v1_path(configured_url)
        self.base_url = self.model_url
        configured_model = str(model_id or os.getenv("EXO_MODEL_ID") or "").strip()
        self._model_id_explicit = bool(configured_model)
        self.model_id = configured_model or DEFAULT_EXO_MODEL_ID
        self.timeout_seconds = timeout_seconds
        self.api_key = os.getenv("EXO_API_KEY", "").strip()

    def get_sandbox_policies(self) -> list[ToolPolicy]:
        """Allow chat calls only to the configured Exo endpoint."""
        parsed = urlsplit(self.model_url)
        allowed_origin = f"{parsed.scheme}://{parsed.netloc}"
        return [
            ToolPolicy(
                name="exo_http",
                paths=[f"{allowed_origin}/**"],
                operations=["chat"],
            )
        ]

    def get_sandbox_actions(self, task_context: dict) -> list[dict]:
        """Declare the endpoint call performed by :meth:`perform_task`."""
        model_url = self._with_v1_path(
            str(task_context.get("model_url") or self.model_url)
        )
        return [
            {
                "tool_name": "exo_http",
                "path": model_url,
                "operation": "chat",
            }
        ]

    def perform_task(self, task_context: dict) -> dict:
        """Execute an LLM task via Exo and return a normalized result payload."""
        messages = self._build_messages(task_context)
        if not messages:
            return {
                "status": "failed",
                "summary": "No prompt or messages provided for LLM processing.",
            }

        temperature = float(task_context.get("temperature", 0.2))
        # 4000 default leaves room for reasoning-mode models (Qwen3.5, o1-style)
        # to produce real content after their thinking budget. The earlier 600
        # was enough for non-reasoning chat models but caused reasoning models
        # to hit the length limit mid-thought and return empty content.
        max_tokens = int(task_context.get("max_tokens", 4000))
        model_url = self._with_v1_path(
            str(task_context.get("model_url") or self.model_url)
        )
        model = self._resolve_model(task_context, model_url)

        self.report_status(
            f"Dispatching {len(messages)} message(s) to Exo model '{model}'."
        )
        try:
            response = self._call_exo(
                messages, model, temperature, max_tokens, model_url
            )
            self.report_status("Exo response received.")
            return {
                "status": "success",
                "summary": response["content"],
                "provider": "exo",
                "model": model,
                "model_url": model_url,
                "usage": response.get("usage", {}),
                "response_id": response.get("id"),
            }
        except Exception as exc:
            fallback = self._build_fallback_summary(model, model_url)
            self.report_status(f"Exo request failed: {exc}")
            return {
                "status": "failed",
                "summary": fallback,
                "provider": "fallback",
                "model": model,
                "model_url": model_url,
                "error": fallback,
                "llm_error": str(exc),
            }

    def _resolve_model(self, task_context: dict, model_url: str) -> str:
        """Resolve an explicit, running, or safe default Exo model ID."""
        task_model = str(task_context.get("model") or "").strip()
        if task_model:
            return task_model
        if self._model_id_explicit:
            return self.model_id
        return self._discover_running_model(model_url) or self.model_id

    def _discover_running_model(self, model_url: str) -> typing.Optional[str]:
        """Return the first model currently loaded by Exo, if available."""
        root = self._with_v1_path(model_url)[: -len("/v1")]
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = requests.get(
                f"{root}/ollama/api/ps",
                headers=headers,
                timeout=min(self.timeout_seconds, 2.0),
            )
            response.raise_for_status()
            models = response.json().get("models", [])
            if not isinstance(models, list):
                return None
            for item in models:
                if not isinstance(item, dict):
                    continue
                model = str(
                    item.get("model") or item.get("name") or item.get("id") or ""
                ).strip()
                if model:
                    return model
        except Exception:  # Discovery is best-effort; the default remains usable.
            return None
        return None

    def _build_messages(self, task_context: dict) -> typing.List[typing.Dict[str, str]]:
        raw_messages = task_context.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            messages: typing.List[typing.Dict[str, str]] = []
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "user"))
                content = str(item.get("content", "")).strip()
                if content:
                    messages.append({"role": role, "content": content})
            if messages:
                return messages

        prompt = str(
            task_context.get("prompt")
            or task_context.get("content")
            or task_context.get("context")
            or task_context.get("query")
            or ""
        ).strip()
        if not prompt:
            return []

        system_prompt = str(task_context.get("system_prompt") or "").strip()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call_exo(
        self,
        messages: typing.List[typing.Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        model_url: str,
    ) -> typing.Dict[str, typing.Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        errors = []
        for endpoint, payload in self._completion_request_candidates(
            messages, model, temperature, max_tokens, model_url, stream=False
        ):
            try:
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
                content = self._extract_message_content(body)
                if not content:
                    raise ValueError("Exo returned no text content.")
                return {
                    "content": content,
                    "usage": body.get("usage", {}),
                    "id": body.get("id"),
                }
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{endpoint}: {exc}")
                if not self._should_try_next_endpoint(exc):
                    break
        raise RuntimeError("Exo request failed after trying " + "; ".join(errors))

    def _completion_request_candidates(
        self,
        messages: typing.List[typing.Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        model_url: str,
        stream: bool,
    ) -> typing.List[tuple[str, typing.Dict[str, typing.Any]]]:
        """Return concrete Exo endpoints to try for one completion request."""
        base = self._with_v1_path(model_url)
        chat_payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        responses_payload = {
            "model": model,
            "input": messages,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "stream": stream,
        }
        return [
            (f"{base}/chat/completions", chat_payload),
            (f"{base}/responses", responses_payload),
        ]

    def _should_try_next_endpoint(self, exc: Exception) -> bool:
        """Retry only when a response suggests the endpoint shape was wrong."""
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code in {400, 404, 405, 422}

    def _with_v1_path(self, url: str) -> str:
        """Normalize ``url`` to Exo's OpenAI-compatible API base path.

        Exo follows the OpenAI spec: callers configure the API base as
        ``<base>/v1``. Earlier callers may pass any of:

        - ``http://host:port``                          -> append ``/v1``
        - ``http://host:port/v1``                       -> leave as-is
        - ``http://host:port/v1/chat/completions``      -> trim to ``/v1``
        - ``http://host:port/v1/anything``              -> trim to ``/v1``

        The stored and returned Exo link should end in ``/v1``. Concrete
        request endpoints are derived from this base.
        """
        endpoint = url.rstrip("/")
        if endpoint.endswith("/v1"):
            return endpoint
        marker = "/v1/"
        if marker in endpoint:
            return endpoint[: endpoint.index(marker) + len("/v1")]
        return f"{endpoint}/v1"

    def _extract_message_content(self, body: typing.Dict[str, typing.Any]) -> str:
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = body.get("output")
        if isinstance(output, list):
            parts = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") in {"output_text", "text"}:
                        text = str(part.get("text") or "").strip()
                        if text:
                            parts.append(text)
            if parts:
                return " ".join(parts)

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("No choices returned from Exo response.")

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {})
        if isinstance(message, dict):
            content = message.get("content", "")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                text = " ".join(part for part in parts if part).strip()
            else:
                text = str(content).strip()
            if text:
                return text
            # Reasoning-mode models (Qwen3.5, o1-style) split their output:
            # ``content`` is the final answer, ``reasoning_content`` is the
            # chain of thought. If the model hit max_tokens during reasoning
            # ``content`` will be empty — surface the reasoning so the user
            # at least sees what the model was thinking about, with a clear
            # marker that the answer was cut off.
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                finish = first.get("finish_reason", "")
                note = (
                    "[Model hit max_tokens during reasoning — increase "
                    "max_tokens to get a final answer.]\n\n"
                    if finish == "length"
                    else "[Model reasoning only — no final content emitted.]\n\n"
                )
                return note + reasoning.strip()
            fallback_text = first.get("text")
            if isinstance(fallback_text, str) and fallback_text.strip():
                return fallback_text.strip()
            return text  # empty, but at least typed correctly

        return str(first.get("text", "")).strip()

    # --- Streaming -----------------------------------------------------
    # Optional capability: the orchestrator's streaming executor checks for
    # ``supports_streaming`` and calls ``stream_task`` when present. Agents
    # without this method are served by single-chunk emission upstream, so
    # adding streaming here doesn't force a change on every other agent.

    supports_streaming = True

    def stream_task(
        self, task_context: dict
    ) -> typing.Iterator[typing.Dict[str, typing.Any]]:
        """Execute an LLM task as a stream of events.

        Yields one event per step::

            {"type": "token", "text": "..."}   # zero or more
            {"type": "final", "result": {...}} # exactly one, last

        The ``final`` event mirrors the dict ``perform_task`` would have
        returned, so the orchestrator can run its normal post-processing
        (memory bus write, Hebbian update) on it.

        When Exo is unreachable, a single failure message is emitted as a
        token followed by a failed terminal result, so the UI stays consistent
        without treating an echoed prompt as a successful LLM completion.
        """
        messages = self._build_messages(task_context)
        if not messages:
            yield {
                "type": "final",
                "result": {
                    "status": "failed",
                    "summary": "No prompt or messages provided for LLM processing.",
                },
            }
            return

        temperature = float(task_context.get("temperature", 0.2))
        max_tokens = int(task_context.get("max_tokens", 4000))
        model_url = self._with_v1_path(
            str(task_context.get("model_url") or self.model_url)
        )
        model = self._resolve_model(task_context, model_url)

        self.report_status(
            f"Streaming {len(messages)} message(s) to Exo model '{model}'."
        )

        chunks: typing.List[str] = []
        try:
            for piece in self._stream_exo(
                messages, model, temperature, max_tokens, model_url
            ):
                if not piece:
                    continue
                chunks.append(piece)
                yield {"type": "token", "text": piece}
            full = "".join(chunks).strip()
            if not full:
                # Exo returned an empty stream (rare but observed) -> fall back.
                raise RuntimeError("Exo stream produced no content")
            self.report_status("Exo stream completed.")
            yield {
                "type": "final",
                "result": {
                    "status": "success",
                    "summary": full,
                    "provider": "exo",
                    "model": model,
                    "model_url": model_url,
                },
            }
        except Exception as exc:  # noqa: BLE001
            fallback = self._build_fallback_summary(model, model_url)
            self.report_status(f"Exo stream failed: {exc}")
            # Emit the fallback as a single token so UI animation still works.
            yield {"type": "token", "text": fallback}
            yield {
                "type": "final",
                "result": {
                    "status": "failed",
                    "summary": fallback,
                    "provider": "fallback",
                    "model": model,
                    "model_url": model_url,
                    "error": fallback,
                    "llm_error": str(exc),
                },
            }

    def _stream_exo(
        self,
        messages: typing.List[typing.Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        model_url: str,
    ) -> typing.Iterator[str]:
        """Yield content deltas from an Exo SSE response.

        Exo follows the OpenAI chat-completions SSE format: lines beginning
        with ``data:`` carry a JSON chunk; the literal line ``data: [DONE]``
        terminates the stream. We extract ``choices[0].delta.content`` from
        each chunk and yield it as a string.
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(
            f"{self._with_v1_path(model_url)}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
            stream=True,
        )
        response.raise_for_status()

        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", "replace").strip()
                else:
                    line = str(raw_line).strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        return
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = self._extract_delta_content(chunk)
                if delta:
                    yield delta
        finally:
            response.close()

    def _extract_delta_content(self, chunk: typing.Dict[str, typing.Any]) -> str:
        """Pull the incremental content out of one Exo SSE JSON chunk."""
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                return "".join(parts)
        # Some servers send the final chunk as message.content instead of delta.
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        return ""

    def _build_fallback_summary(self, model: str, model_url: str) -> str:
        return (
            f"LLM execution unavailable: Exo could not serve model '{model}' at "
            f"{model_url}. Start the model in Exo or set EXO_MODEL_ID to a "
            "model available to the cluster."
        )
