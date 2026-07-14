import random
import time

from .base_agent import BaseAgent
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

        if task_context.get("disable_llm_delegate") is not True:
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
                }
            )
            if llm_result.get("status") == "success":
                summary = llm_result.get("summary", "")
                return {
                    "status": "success",
                    "summary": summary,
                    "findings": [summary],
                    "sources_consulted": [
                        f"LLM provider: {llm_result.get('provider', 'unknown')}"
                    ],
                    "recommendations": [
                        "Validate cited claims with primary sources.",
                    ],
                }

        self.report_status(f"Starting research on '{topic}' with depth '{depth}'...")
        self.report_status(f"Keywords: {', '.join(keywords)}")

        # Simulate research activity
        time.sleep(random.uniform(2, 5))

        # Simulate findings
        findings = [
            f"Found key paper on {topic} by Author A (2023).",
            "Relevant data set discovered at Source B.",
            f"Emerging trend: X in {topic} field.",
        ]

        summary = (
            f"Initial research on '{topic}' has been completed. "
            f"Key findings indicate {random.choice(['significant progress', 'new challenges', 'interesting paradigms'])}. "
            f"Further investigation into specific areas like {random.choice(keywords) or 'data analysis'} is recommended."
        )

        self.report_status("Research completed.")
        return {
            "status": "success",
            "summary": summary,
            "findings": findings,
            "sources_consulted": [
                f"Simulated academic database for {topic}",
                f"Simulated online encyclopedia for {topic}",
            ],
            "recommendations": [
                "Follow up on Author A's work",
                "Analyze Source B data",
            ],
        }
