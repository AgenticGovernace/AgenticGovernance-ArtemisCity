"""LLM-backed agent implementation with Exo-compatible chat completion calls."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from .base_agent import BaseAgent


class LLMAgent(BaseAgent):
    """Route prompt-style tasks to an Exo/OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        name: str = "LLM Agent",
        base_url: Optional[str] = None,
        model_id: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            name,
            capabilities=[
                "llm_chat",
                "text_generation",
                "reasoning",
            ],
        )
        self.base_url = (
            base_url or os.getenv("EXO_BASE_URL", "http://localhost:52415")
        ).rstrip("/")
        self.model_id = model_id or os.getenv("EXO_MODEL_ID", "gpt-4o-2024-08-06")
        self.timeout_seconds = timeout_seconds
        self.api_key = os.getenv("EXO_API_KEY", "").strip()

    def perform_task(self, task_context: dict) -> dict:
        """Execute an LLM task via Exo and return a normalized result payload."""
        messages = self._build_messages(task_context)
        if not messages:
            return {
                "status": "failed",
                "summary": "No prompt or messages provided for LLM processing.",
            }

        temperature = float(task_context.get("temperature", 0.2))
        max_tokens = int(task_context.get("max_tokens", 600))
        model = str(task_context.get("model") or self.model_id)

        self.report_status(
            f"Dispatching {len(messages)} message(s) to Exo model '{model}'."
        )
        try:
            response = self._call_exo(messages, model, temperature, max_tokens)
            self.report_status("Exo response received.")
            return {
                "status": "success",
                "summary": response["content"],
                "provider": "exo",
                "model": model,
                "usage": response.get("usage", {}),
                "response_id": response.get("id"),
            }
        except Exception as exc:
            # Keep the system usable when Exo is offline while surfacing the reason.
            fallback = self._build_fallback_summary(messages)
            self.report_status(f"Exo request failed, using fallback response: {exc}")
            return {
                "status": "success",
                "summary": fallback,
                "provider": "fallback",
                "model": model,
                "llm_error": str(exc),
            }

    def _build_messages(self, task_context: dict) -> List[Dict[str, str]]:
        raw_messages = task_context.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            messages: List[Dict[str, str]] = []
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
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        api_base = self.base_url
        if not api_base.endswith("/v1"):
            api_base = f"{api_base}/v1"
        endpoint = f"{api_base}/chat/completions"

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
            return {
                "content": content,
                "usage": body.get("usage", {}),
                "id": body.get("id"),
            }
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Exo request failed at {endpoint}: {exc}") from exc

    def _extract_message_content(self, body: Dict[str, Any]) -> str:
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
                return " ".join(part for part in parts if part).strip()
            return str(content).strip()

        return str(first.get("text", "")).strip()

    def _build_fallback_summary(self, messages: List[Dict[str, str]]) -> str:
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        prompt = user_messages[-1] if user_messages else messages[-1]["content"]
        snippet = prompt[:220].replace("\n", " ").strip()
        if len(prompt) > 220:
            snippet += "..."
        return (
            "Fallback response: Exo is unavailable right now. "
            f"Received prompt: {snippet}"
        )
