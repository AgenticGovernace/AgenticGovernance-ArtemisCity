"""LLM-backed agent implementation with Exo model endpoint calls."""

from __future__ import annotations

import hashlib
import json
import os
import time
import typing
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from src.integration.sandbox import ToolPolicy

from . import base_agent

DEFAULT_EXO_BASE_URL = "http://localhost:52415"
DEFAULT_EXO_MODEL_ID = "mlx-community/Qwen3-0.6B-4bit"
DEFAULT_EXO_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_EXO_READ_TIMEOUT_SECONDS = 900.0
DEFAULT_EXO_MAX_RETRIES = 2
DEFAULT_EXO_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_EXO_RETRY_MAX_DELAY_SECONDS = 60.0
_TRANSIENT_HTTP_STATUSES = {429, 502, 503, 504}


class _ExoRequestError(RuntimeError):
    """Transport failure that retains redacted request-attempt evidence."""

    def __init__(self, message: str, request_metadata: dict[str, typing.Any]) -> None:
        super().__init__(message)
        self.request_metadata = request_metadata


def _env_float(name: str, default: float) -> float:
    """Read a non-negative float without making bad environment data fatal."""
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    """Read a bounded retry count without making bad environment data fatal."""
    try:
        return min(10, max(0, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


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
    """Route prompt-style tasks to the configured Exo model endpoint.

    Connections fail fast after 10 seconds by default, while model generation
    may run for 900 seconds. Operators can tune those independently with
    ``EXO_CONNECT_TIMEOUT_SECONDS`` and ``EXO_READ_TIMEOUT_SECONDS``; setting
    the read timeout to ``0`` waits without a read deadline. The legacy
    ``timeout_seconds`` constructor argument still sets both sides when used.
    """

    def __init__(
        self,
        name: str = "LLM Agent",
        base_url: typing.Optional[str] = None,
        model_url: typing.Optional[str] = None,
        model_id: typing.Optional[str] = None,
        timeout_seconds: typing.Optional[float] = None,
        connect_timeout_seconds: typing.Optional[float] = None,
        read_timeout_seconds: typing.Optional[float] = None,
        max_retries: typing.Optional[int] = None,
        retry_backoff_seconds: typing.Optional[float] = None,
        retry_max_delay_seconds: typing.Optional[float] = None,
    ) -> None:
        super().__init__(
            name,
            capabilities=[
                "llm_chat",
                "text_generation",
                "reasoning",
                "text_summarization",
                # Aliases so common generic requests route here.
                "chat",
                "general",
                "inference",
            ],
        )
        configured_url = (
            model_url
            or base_url
            or os.getenv("EXO_MODEL_URL")
            or os.getenv("EXO_BASE_URL", DEFAULT_EXO_BASE_URL)
        )
        self.model_url = self._with_v1_path(configured_url)
        self.base_url = self.model_url
        configured_model = str(model_id or os.getenv("EXO_MODEL_ID") or "").strip()
        self._model_id_explicit = bool(configured_model)
        self.model_id = configured_model or DEFAULT_EXO_MODEL_ID
        legacy_timeout = (
            max(0.0, float(timeout_seconds)) if timeout_seconds is not None else None
        )
        configured_connect = (
            float(connect_timeout_seconds)
            if connect_timeout_seconds is not None
            else (
                legacy_timeout
                if legacy_timeout is not None
                else _env_float(
                    "EXO_CONNECT_TIMEOUT_SECONDS",
                    DEFAULT_EXO_CONNECT_TIMEOUT_SECONDS,
                )
            )
        )
        configured_read = (
            float(read_timeout_seconds)
            if read_timeout_seconds is not None
            else (
                legacy_timeout
                if legacy_timeout is not None
                else _env_float(
                    "EXO_READ_TIMEOUT_SECONDS", DEFAULT_EXO_READ_TIMEOUT_SECONDS
                )
            )
        )
        self.connect_timeout_seconds = max(0.001, configured_connect)
        # A zero read timeout explicitly means "wait indefinitely for Exo".
        self.read_timeout_seconds: typing.Optional[float] = (
            max(0.001, configured_read) if configured_read > 0 else None
        )
        # Preserve the legacy public attribute for callers that inspect it.
        self.timeout_seconds = self.read_timeout_seconds or 0.0
        self.request_timeout = (
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
        )
        self.max_retries = min(
            10,
            max(
                0,
                (
                    int(max_retries)
                    if max_retries is not None
                    else _env_int("EXO_MAX_RETRIES", DEFAULT_EXO_MAX_RETRIES)
                ),
            ),
        )
        self.retry_backoff_seconds = max(
            0.0,
            (
                float(retry_backoff_seconds)
                if retry_backoff_seconds is not None
                else _env_float(
                    "EXO_RETRY_BACKOFF_SECONDS", DEFAULT_EXO_RETRY_BACKOFF_SECONDS
                )
            ),
        )
        self.retry_max_delay_seconds = max(
            0.0,
            (
                float(retry_max_delay_seconds)
                if retry_max_delay_seconds is not None
                else _env_float(
                    "EXO_RETRY_MAX_DELAY_SECONDS",
                    DEFAULT_EXO_RETRY_MAX_DELAY_SECONDS,
                )
            ),
        )
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
            exo_request = response["exo_request"]
            incomplete_summary = self._incomplete_summary_result(
                response.get("content", ""), exo_request, model, model_url
            )
            if incomplete_summary is not None:
                self.report_status(
                    "Exo response did not contain a final answer; marking the "
                    "provider result incomplete."
                )
                return incomplete_summary
            self.report_status(
                "Exo response received "
                f"(request_id={exo_request['request_id']}, "
                f"endpoint={exo_request['endpoint']}, "
                f"status={exo_request['http_status']}, "
                f"latency_ms={exo_request['latency_ms']}, "
                f"response_id={exo_request.get('response_id')}, "
                f"response_model={exo_request.get('response_model')}, "
                f"content_sha256={exo_request.get('content_sha256')})."
            )
            return {
                "status": "success",
                "summary": response["content"],
                "raw_output": response["content"],
                "provider": "exo",
                "fallback_used": False,
                "outcome_class": "success",
                "learning_eligible": True,
                "model": model,
                "model_url": model_url,
                "usage": response.get("usage", {}),
                "response_id": response.get("id"),
                "exo_request": exo_request,
            }
        except Exception as exc:
            failure_summary = self._build_failure_summary(model, model_url)
            self.report_status(f"Exo request failed: {exc}")
            result = {
                "status": "failed",
                "summary": failure_summary,
                "provider": "exo",
                "fallback_used": False,
                "model": model,
                "model_url": model_url,
                "error": failure_summary,
                "llm_error": str(exc),
            }
            request_metadata = getattr(exc, "request_metadata", None)
            if isinstance(request_metadata, dict):
                result.update(self._provider_failure_fields(request_metadata))
                result["exo_request"] = request_metadata
            return result

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
            discovery_timeout = min(
                self.connect_timeout_seconds,
                self.read_timeout_seconds or 2.0,
                2.0,
            )
            response = requests.get(
                f"{root}/ollama/api/ps",
                headers=headers,
                timeout=discovery_timeout,
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
        request_id = str(uuid.uuid4())
        headers = self._request_headers(request_id=request_id, stream=False)
        started = time.monotonic()
        attempts: list[dict[str, typing.Any]] = []
        errors: list[str] = []
        last_endpoint: typing.Optional[str] = None
        last_status: typing.Optional[int] = None
        last_kind = "transport_error"
        last_retryable = False

        for endpoint, payload in self._completion_request_candidates(
            messages, model, temperature, max_tokens, model_url, stream=False
        ):
            last_endpoint = endpoint
            endpoint_error: typing.Optional[Exception] = None
            for retry_index in range(self.max_retries + 1):
                response = None
                attempt_started = time.monotonic()
                try:
                    response = requests.post(
                        endpoint,
                        json=payload,
                        headers=headers,
                        timeout=self.request_timeout,
                    )
                    response.raise_for_status()
                    body = response.json()
                    content = self._extract_message_content(body)
                    if not content:
                        raise ValueError("Exo returned no text content.")
                    status = self._response_status(response)
                    attempts.append(
                        self._attempt_record(
                            endpoint,
                            retry_index,
                            attempt_started,
                            status,
                            outcome="success",
                        )
                    )
                    metadata = self._success_request_metadata(
                        request_id=request_id,
                        endpoint=endpoint,
                        response=response,
                        body=body,
                        content=content,
                        requested_model=model,
                        started=started,
                        attempts=attempts,
                    )
                    return {
                        "content": content,
                        "usage": body.get("usage", {}),
                        "id": metadata.get("response_id"),
                        "exo_request": metadata,
                    }
                except Exception as exc:  # noqa: BLE001
                    endpoint_error = exc
                    status = self._response_status(response) or self._exception_status(
                        exc
                    )
                    failure_kind, retryable = self._classify_failure(exc, status)
                    last_status = status
                    last_kind = failure_kind
                    last_retryable = retryable
                    retry_response = (
                        response
                        if self._response_status(response) is not None
                        else getattr(exc, "response", None)
                    )
                    record = self._attempt_record(
                        endpoint,
                        retry_index,
                        attempt_started,
                        status,
                        outcome="failed",
                        # Class name only: attempt records ship to clients in
                        # exo_request (CodeQL py/stack-trace-exposure).
                        error=type(exc).__name__,
                        failure_kind=failure_kind,
                    )
                    retry_after = self._retry_after_seconds(retry_response)
                    if retry_after is not None:
                        record["retry_after_seconds"] = retry_after
                    attempts.append(record)
                    if retryable and retry_index < self.max_retries:
                        delay = self._retry_delay_seconds(retry_index, retry_response)
                        record["retry_delay_seconds"] = delay
                        if delay:
                            time.sleep(delay)
                        continue
                    break
                finally:
                    if response is not None:
                        response.close()

            assert (
                endpoint_error is not None
            )  # loop invariant: every failure path records endpoint_error  # nosec B101
            errors.append(f"{endpoint}: {endpoint_error}")
            if not self._should_try_next_endpoint(endpoint_error):
                break

        metadata = self._failure_request_metadata(
            request_id=request_id,
            endpoint=last_endpoint,
            status=last_status,
            requested_model=model,
            started=started,
            attempts=attempts,
            failure_kind=last_kind,
            retryable=last_retryable,
        )
        raise _ExoRequestError(
            "Exo request failed after trying " + "; ".join(errors), metadata
        )

    def _request_headers(self, *, request_id: str, stream: bool) -> dict[str, str]:
        """Build transport headers without ever copying credentials to results."""
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
            "X-Artemis-Agent": self.name,
        }
        if stream:
            headers["Accept"] = "text/event-stream"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _attempt_record(
        self,
        endpoint: str,
        retry_index: int,
        started: float,
        status: typing.Optional[int],
        *,
        outcome: str,
        error: typing.Optional[str] = None,
        failure_kind: typing.Optional[str] = None,
    ) -> dict[str, typing.Any]:
        record: dict[str, typing.Any] = {
            "attempt": retry_index + 1,
            "endpoint": endpoint,
            "http_status": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "outcome": outcome,
        }
        if error is not None:
            record["error"] = error
        if failure_kind is not None:
            record["failure_kind"] = failure_kind
        return record

    def _success_request_metadata(
        self,
        *,
        request_id: str,
        endpoint: str,
        response: typing.Any,
        body: dict[str, typing.Any],
        content: str,
        requested_model: str,
        started: float,
        attempts: list[dict[str, typing.Any]],
    ) -> dict[str, typing.Any]:
        response_id, response_model = self._response_identity(body)
        return {
            "request_id": request_id,
            "server_request_id": self._server_request_id(response),
            "endpoint": endpoint,
            "http_status": self._response_status(response),
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "requested_model": requested_model,
            "response_id": response_id,
            "response_model": response_model,
            "content_length": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "attempt_count": len(attempts),
            "attempts": attempts,
        }

    def _failure_request_metadata(
        self,
        *,
        request_id: str,
        endpoint: typing.Optional[str],
        status: typing.Optional[int],
        requested_model: str,
        started: float,
        attempts: list[dict[str, typing.Any]],
        failure_kind: str,
        retryable: bool,
    ) -> dict[str, typing.Any]:
        metadata = {
            "request_id": request_id,
            "endpoint": endpoint,
            "http_status": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "requested_model": requested_model,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "failure_kind": failure_kind,
            "retryable": retryable,
        }
        for attempt in reversed(attempts):
            retry_after = attempt.get("retry_after_seconds")
            if isinstance(retry_after, (int, float)) and not isinstance(
                retry_after, bool
            ):
                metadata["retry_after_seconds"] = max(0.0, float(retry_after))
                break
        return metadata

    def _provider_failure_fields(
        self, request_metadata: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Describe provider availability separately from agent task quality."""
        return {
            "outcome_class": "provider_failure",
            "learning_eligible": False,
            "failure_kind": request_metadata.get("failure_kind", "transport_error"),
            "retryable": bool(request_metadata.get("retryable", False)),
            "upstream_status_code": request_metadata.get("http_status"),
            "attempt_count": int(request_metadata.get("attempt_count", 0)),
            "retry_after_seconds": request_metadata.get("retry_after_seconds"),
        }

    def _response_status(self, response: typing.Any) -> typing.Optional[int]:
        status = getattr(response, "status_code", None)
        return status if isinstance(status, int) else None

    def _exception_status(self, exc: Exception) -> typing.Optional[int]:
        return self._response_status(getattr(exc, "response", None))

    def _server_request_id(self, response: typing.Any) -> typing.Optional[str]:
        headers = getattr(response, "headers", None)
        if headers is None or not hasattr(headers, "get"):
            return None
        for name in ("X-Request-ID", "Request-ID", "X-Correlation-ID"):
            value = headers.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _response_identity(
        self, body: dict[str, typing.Any]
    ) -> tuple[typing.Optional[str], typing.Optional[str]]:
        nested = body.get("response")
        nested = nested if isinstance(nested, dict) else {}
        response_id = body.get("id") or nested.get("id")
        response_model = body.get("model") or nested.get("model")
        return (
            str(response_id) if isinstance(response_id, (str, int)) else None,
            str(response_model) if isinstance(response_model, (str, int)) else None,
        )

    def _classify_failure(
        self, exc: Exception, status: typing.Optional[int]
    ) -> tuple[str, bool]:
        if isinstance(exc, (ValueError, json.JSONDecodeError)):
            return "invalid_response", False
        name = type(exc).__name__.lower()
        detail = str(exc).lower()
        if "readtimeout" in name or "read timed out" in detail:
            return "read_timeout", False
        if (
            "connecttimeout" in name
            or "connectionerror" in name
            or "connection refused" in detail
            or "failed to establish a new connection" in detail
            or "connection failed" in detail
        ):
            return "connect_timeout", True
        if status == 429:
            return "rate_limited", True
        if status is not None and status >= 400:
            return "http_error", status in _TRANSIENT_HTTP_STATUSES
        return "transport_error", False

    def _retry_delay_seconds(self, retry_index: int, response: typing.Any) -> float:
        retry_after = self._retry_after_seconds(response)
        if retry_after is None:
            retry_after = self.retry_backoff_seconds * (2**retry_index)
        return min(max(0.0, retry_after), self.retry_max_delay_seconds)

    def _retry_after_seconds(self, response: typing.Any) -> typing.Optional[float]:
        headers = getattr(response, "headers", None)
        if headers is None or not hasattr(headers, "get"):
            return None
        raw = headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
        try:
            retry_at = parsedate_to_datetime(str(raw))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

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

    @staticmethod
    def _incomplete_summary_result(
        content: typing.Any,
        exo_request: dict[str, typing.Any],
        model: str,
        model_url: str,
    ) -> typing.Optional[dict[str, typing.Any]]:
        """Reject reasoning-only output before it reaches downstream agents."""
        if not isinstance(content, str):
            return None
        if not content.startswith(
            (
                "[Model hit max_tokens during reasoning",
                "[Model reasoning only — no final content emitted.]",
            )
        ):
            return None
        return {
            "status": "failed",
            "summary": "[Model hit max_tokens during reasoning; no final answer emitted.]",
            "provider": "exo",
            "fallback_used": False,
            "outcome_class": "provider_failure",
            "learning_eligible": False,
            "model": model,
            "model_url": model_url,
            "error": content,
            "exo_request": exo_request,
        }

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

        When Exo is unreachable, no substitute token is emitted. The stream
        ends with a failed terminal result carrying explicit provider evidence.
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
            stream = self._stream_exo(
                messages, model, temperature, max_tokens, model_url
            )
            exo_request: dict[str, typing.Any] = {}
            while True:
                try:
                    piece = next(stream)
                except StopIteration as completed:
                    if isinstance(completed.value, dict):
                        exo_request = completed.value
                    break
                if not piece:
                    continue
                chunks.append(piece)
                yield {"type": "token", "text": piece}
            full = "".join(chunks)
            if not full.strip():
                # Exo returned an empty stream (rare but observed) -> fail with
                # the same provider evidence rather than claiming model success.
                exo_request["failure_kind"] = "invalid_response"
                exo_request["retryable"] = False
                raise _ExoRequestError("Exo stream produced no content", exo_request)
            self.report_status(
                "Exo stream completed "
                f"(request_id={exo_request.get('request_id')}, "
                f"endpoint={exo_request.get('endpoint')}, "
                f"status={exo_request.get('http_status')}, "
                f"latency_ms={exo_request.get('latency_ms')}, "
                f"response_id={exo_request.get('response_id')}, "
                f"response_model={exo_request.get('response_model')}, "
                f"content_sha256={exo_request.get('content_sha256')})."
            )
            yield {
                "type": "final",
                "result": {
                    "status": "success",
                    "summary": full,
                    "raw_output": full,
                    "provider": "exo",
                    "fallback_used": False,
                    "outcome_class": "success",
                    "learning_eligible": True,
                    "model": model,
                    "model_url": model_url,
                    "response_id": exo_request.get("response_id"),
                    "exo_request": exo_request,
                },
            }
        except Exception as exc:  # noqa: BLE001
            failure_summary = self._build_failure_summary(model, model_url)
            self.report_status(f"Exo stream failed: {exc}")
            result = {
                "status": "failed",
                "summary": failure_summary,
                "provider": "exo",
                "fallback_used": False,
                "model": model,
                "model_url": model_url,
                "error": failure_summary,
                "llm_error": str(exc),
            }
            request_metadata = getattr(exc, "request_metadata", None)
            if isinstance(request_metadata, dict):
                result.update(self._provider_failure_fields(request_metadata))
                result["exo_request"] = request_metadata
            yield {
                "type": "final",
                "result": result,
            }

    def _stream_exo(
        self,
        messages: typing.List[typing.Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        model_url: str,
    ) -> typing.Generator[str, None, dict[str, typing.Any]]:
        """Yield content deltas from an Exo SSE response.

        Chat Completions SSE is attempted first, followed by Responses SSE
        when the first endpoint returns a compatibility status. ``data:`` JSON
        chunks are normalized from either ``choices[0].delta.content`` or
        Responses ``response.output_text.*`` events. A literal ``[DONE]``
        terminates either stream.
        """
        request_id = str(uuid.uuid4())
        headers = self._request_headers(request_id=request_id, stream=True)
        started = time.monotonic()
        attempts: list[dict[str, typing.Any]] = []
        errors: list[str] = []
        last_endpoint: typing.Optional[str] = None
        last_status: typing.Optional[int] = None
        last_kind = "transport_error"
        last_retryable = False

        for endpoint, payload in self._completion_request_candidates(
            messages, model, temperature, max_tokens, model_url, stream=True
        ):
            last_endpoint = endpoint
            endpoint_error: typing.Optional[Exception] = None
            for retry_index in range(self.max_retries + 1):
                response = None
                response_started = False
                emitted_content = False
                content_parts: list[str] = []
                response_body: dict[str, typing.Any] = {}
                attempt_started = time.monotonic()
                try:
                    response = requests.post(
                        endpoint,
                        json=payload,
                        headers=headers,
                        timeout=self.request_timeout,
                        stream=True,
                    )
                    response.raise_for_status()
                    response_started = True

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
                                break
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        response_id, response_model = self._response_identity(chunk)
                        if response_id is not None:
                            response_body["id"] = response_id
                        if response_model is not None:
                            response_body["model"] = response_model
                        delta = self._extract_delta_content(chunk)
                        is_final_text = chunk.get("type") in {
                            "response.output_text.done",
                            "response.completed",
                        }
                        if delta and not (is_final_text and emitted_content):
                            emitted_content = True
                            content_parts.append(delta)
                            yield delta
                    status = self._response_status(response)
                    attempts.append(
                        self._attempt_record(
                            endpoint,
                            retry_index,
                            attempt_started,
                            status,
                            outcome="success",
                        )
                    )
                    return self._success_request_metadata(
                        request_id=request_id,
                        endpoint=endpoint,
                        response=response,
                        body=response_body,
                        content="".join(content_parts),
                        requested_model=model,
                        started=started,
                        attempts=attempts,
                    )
                except Exception as exc:  # noqa: BLE001
                    endpoint_error = exc
                    status = self._response_status(response) or self._exception_status(
                        exc
                    )
                    failure_kind, retryable = self._classify_failure(exc, status)
                    last_status = status
                    last_kind = failure_kind
                    safely_retryable = (
                        retryable and not response_started and not emitted_content
                    )
                    last_retryable = safely_retryable
                    retry_response = (
                        response
                        if self._response_status(response) is not None
                        else getattr(exc, "response", None)
                    )
                    record = self._attempt_record(
                        endpoint,
                        retry_index,
                        attempt_started,
                        status,
                        outcome="failed",
                        # Class name only: attempt records ship to clients in
                        # exo_request (CodeQL py/stack-trace-exposure).
                        error=type(exc).__name__,
                        failure_kind=failure_kind,
                    )
                    retry_after = self._retry_after_seconds(retry_response)
                    if retry_after is not None:
                        record["retry_after_seconds"] = retry_after
                    attempts.append(record)
                    # Once headers/body processing starts, replaying could duplicate
                    # generated tokens. Read timeouts and partial streams therefore
                    # fail as-is; only pre-response connection/transient failures retry.
                    can_retry = safely_retryable and retry_index < self.max_retries
                    if can_retry:
                        delay = self._retry_delay_seconds(retry_index, retry_response)
                        record["retry_delay_seconds"] = delay
                        if delay:
                            time.sleep(delay)
                        continue
                    break
                finally:
                    if response is not None:
                        response.close()

            assert (
                endpoint_error is not None
            )  # loop invariant: every failure path records endpoint_error  # nosec B101
            errors.append(f"{endpoint}: {endpoint_error}")
            if emitted_content or not self._should_try_next_endpoint(endpoint_error):
                break

        metadata = self._failure_request_metadata(
            request_id=request_id,
            endpoint=last_endpoint,
            status=last_status,
            requested_model=model,
            started=started,
            attempts=attempts,
            failure_kind=last_kind,
            retryable=last_retryable,
        )
        raise _ExoRequestError(
            "Exo stream failed after trying " + "; ".join(errors), metadata
        )

    def _extract_delta_content(self, chunk: typing.Dict[str, typing.Any]) -> str:
        """Pull the incremental content out of one Exo SSE JSON chunk."""
        event_type = chunk.get("type")
        if event_type == "response.output_text.delta":
            delta = chunk.get("delta")
            return delta if isinstance(delta, str) else ""
        if event_type == "response.output_text.done":
            text = chunk.get("text")
            return text if isinstance(text, str) else ""
        if event_type == "response.completed":
            response = chunk.get("response")
            if isinstance(response, dict):
                try:
                    return self._extract_message_content(response)
                except ValueError:
                    return ""

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

    def _build_failure_summary(self, model: str, model_url: str) -> str:
        """Describe an Exo failure without fabricating substitute model output."""
        return (
            f"LLM execution unavailable: Exo could not serve model '{model}' at "
            f"{model_url}. Start the model in Exo or set EXO_MODEL_ID to a "
            "model available to the cluster."
        )
