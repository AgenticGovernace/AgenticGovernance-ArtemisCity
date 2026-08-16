import json
from typing import Optional

from .base_agent import BaseAgent
from .fallback_policy import (
    degraded_metadata,
    provider_failure_result,
    synthetic_fallback_enabled,
)
from .llm_agent import LLMAgent


class SummarizerAgent(BaseAgent):
    """Implement the text-summarization agent used by the orchestrator."""

    def __init__(
        self,
        name: str = "Summarizer Agent",
        llm_agent: Optional[LLMAgent] = None,
    ):
        super().__init__(name, capabilities=["text_summarization"])
        self.llm_agent = llm_agent or LLMAgent()

    def get_sandbox_policies(self) -> list:
        return self.llm_agent.get_sandbox_policies()

    def get_sandbox_actions(self, task_context: dict) -> list[dict]:
        if task_context.get("disable_llm_delegate") is True:
            return []
        return self.llm_agent.get_sandbox_actions(task_context)

    def perform_task(self, task_context: dict) -> dict:
        """Perform task.

        Args:
            task_context (dict): Structured task context passed to the agent.

        Returns:
            dict: Dictionary containing the resulting data.
        """
        text_to_summarize = task_context.get("content", "")
        if not text_to_summarize:
            self.report_status("No content provided to summarize.")
            return {
                "status": "failed",
                "summary": "No content was provided for summarization.",
            }

        disable_delegate = task_context.get("disable_llm_delegate") is True
        llm_result = None
        if not disable_delegate:
            source_context = task_context.get("source_context")
            context_block = ""
            if isinstance(source_context, dict) and source_context:
                context_block = (
                    "\n\nShared source context (use this to retain the requester intent "
                    "and highlight important points):\n"
                    + json.dumps(source_context, sort_keys=True, default=str)
                )
            llm_result = self.llm_agent.perform_task(
                {
                    "task_id": task_context.get("task_id"),
                    "system_prompt": (
                        "Summarize the supplied model output clearly and accurately for "
                        "a follow-on agent. Preserve decisions, constraints, evidence, "
                        "uncertainties, and next actions. Highlight the most important "
                        "points; do not invent facts."
                    ),
                    "prompt": text_to_summarize + context_block,
                    "temperature": task_context.get("temperature", 0.1),
                    "max_tokens": task_context.get("max_tokens", 400),
                    "model": task_context.get("model"),
                    "model_url": task_context.get("model_url"),
                }
            )
            if llm_result.get("status") == "success":
                summary = llm_result.get("summary", "")
                return {
                    "status": "success",
                    "original_length": len(text_to_summarize),
                    "summary": summary,
                    "raw_output": llm_result.get("raw_output", summary),
                    "summary_length": len(summary),
                    "main_points_extracted": [
                        "LLM-generated concise summary.",
                    ],
                    "provider": llm_result.get("provider"),
                    "fallback_used": llm_result.get("fallback_used", False),
                    "outcome_class": llm_result.get("outcome_class", "success"),
                    "learning_eligible": llm_result.get("learning_eligible", True),
                    "model": llm_result.get("model"),
                    "model_url": llm_result.get("model_url"),
                    "usage": llm_result.get("usage", {}),
                    "response_id": llm_result.get("response_id"),
                    "exo_request": llm_result.get("exo_request"),
                }

            if not synthetic_fallback_enabled(task_context):
                return provider_failure_result(llm_result, agent_name=self.name)

        self.report_status(
            "Using the explicitly enabled local extractive summarization baseline "
            f"(length: {len(text_to_summarize)} chars)."
        )

        # Deterministic demonstration baseline. It is deliberately labelled and
        # excluded from learning so it cannot masquerade as Exo quality.
        words = text_to_summarize.split()
        summary_length = min(max(1, len(words) // 5), 100)
        summary_words = words[:summary_length]
        summary = (
            " ".join(summary_words) + "..."
            if len(words) > summary_length
            else " ".join(summary_words)
        )

        self.report_status("Summarization completed.")
        reason = "llm_delegate_disabled" if disable_delegate else "provider_unavailable"
        result = {
            "status": "success",
            "original_length": len(text_to_summarize),
            "summary": summary,
            "summary_length": len(summary),
            "main_points_extracted": [
                "Identified main topic based on initial words.",
                "Extracted key phrases.",
            ],
            "performance_score": 0.25,
        }
        result.update(degraded_metadata("extractive_fallback", reason))
        if llm_result is not None:
            result["delegate_failure"] = llm_result.get("delegate_failure", llm_result)
        return result
