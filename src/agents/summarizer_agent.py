import time

from .base_agent import BaseAgent
from .llm_agent import LLMAgent


class SummarizerAgent(BaseAgent):
    """Implement the text-summarization agent used by the orchestrator."""

    def __init__(self, name: str = "Summarizer Agent"):
        super().__init__(name, capabilities=["text_summarization"])
        self.llm_agent = LLMAgent()

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

        if task_context.get("disable_llm_delegate") is not True:
            llm_result = self.llm_agent.perform_task(
                {
                    "task_id": task_context.get("task_id"),
                    "system_prompt": "Summarize user content clearly and accurately.",
                    "prompt": text_to_summarize,
                    "temperature": task_context.get("temperature", 0.1),
                    "max_tokens": task_context.get("max_tokens", 400),
                    "model": task_context.get("model"),
                }
            )
            if llm_result.get("status") == "success":
                summary = llm_result.get("summary", "")
                return {
                    "status": "success",
                    "original_length": len(text_to_summarize),
                    "summary": summary,
                    "summary_length": len(summary),
                    "main_points_extracted": [
                        "LLM-generated concise summary.",
                    ],
                    "provider": llm_result.get("provider"),
                }

        self.report_status(
            f"Starting summarization of content (length: {len(text_to_summarize)} chars)..."
        )
        time.sleep(1)  # Simulate processing

        # Simple summarization for demonstration
        words = text_to_summarize.split()
        summary_length = min(len(words) // 5, 100)  # Roughly 20% of words, max 100
        summary_words = words[:summary_length]
        summary = (
            " ".join(summary_words) + "..."
            if len(words) > summary_length
            else " ".join(summary_words)
        )

        self.report_status("Summarization completed.")
        return {
            "status": "success",
            "original_length": len(text_to_summarize),
            "summary": summary,
            "summary_length": len(summary),
            "main_points_extracted": [
                "Identified main topic based on initial words.",
                "Extracted key phrases.",
            ],
        }
