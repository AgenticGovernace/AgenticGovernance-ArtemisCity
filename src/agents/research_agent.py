from .base_agent import BaseAgent
from .fallback_policy import (degraded_metadata, provider_failure_result,
                              synthetic_fallback_enabled)
from .llm_agent import LLMAgent


class ResearchAgent(BaseAgent):
    """Implement the research-oriented agent used for discovery tasks."""

    def __init__(self, name: str = "Research Agent"):
        super().__init__(name, capabilities=["web_search", "document_analysis"])
        self.llm_agent = LLMAgent()

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
        topic = task_context.get("topic", task_context.get("title", "unknown topic"))
        keywords = task_context.get("keywords", "").split(",")
        depth = task_context.get("depth", "overview")

        disable_delegate = task_context.get("disable_llm_delegate") is True
        llm_result = None
        if not disable_delegate:
            prompt = (
                f"Research topic: {topic}\n"
                f"Depth: {depth}\n"
                f"Keywords: {', '.join(k.strip() for k in keywords if k.strip()) or 'none'}\n\n"
                "Provide:\n"
                "1) concise summary\n"
                "2) key findings\n"
                "3) recommended next steps"
            )
            llm_result = self.llm_agent.perform_task(
                {
                    "task_id": task_context.get("task_id"),
                    "system_prompt": "You are a concise research assistant.",
                    "prompt": prompt,
                    "temperature": task_context.get("temperature", 0.2),
                    "max_tokens": task_context.get("max_tokens", 700),
                    "model": task_context.get("model"),
                    "model_url": task_context.get("model_url"),
                }
            )
            if llm_result.get("status") == "success":
                summary = llm_result.get("summary", "")
                return {
                    "status": "success",
                    "summary": summary,
                    "raw_output": llm_result.get("raw_output", summary),
                    "findings": [summary],
                    "sources_consulted": [
                        f"LLM provider: {llm_result.get('provider', 'unknown')}"
                    ],
                    "recommendations": [
                        "Validate cited claims with primary sources.",
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
            "Using the explicitly enabled local research planning baseline; "
            "no external research source was queried."
        )
        normalized_keywords = [item.strip() for item in keywords if item.strip()]
        summary = (
            f"A research plan was prepared for '{topic}' at {depth} depth. "
            "No model or external source results are included."
        )
        result = {
            "status": "success",
            "summary": summary,
            "findings": [],
            "sources_consulted": [],
            "recommendations": [
                "Query primary sources before treating this plan as research output.",
                "Prioritize: " + (", ".join(normalized_keywords) or "topic discovery"),
            ],
            "performance_score": 0.0,
        }
        reason = "llm_delegate_disabled" if disable_delegate else "provider_unavailable"
        result.update(degraded_metadata("research_planning_fallback", reason))
        if llm_result is not None:
            result["delegate_failure"] = llm_result
        return result
