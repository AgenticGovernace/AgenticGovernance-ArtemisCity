from .base_agent import BaseAgent
import time
import random


class ResearchAgent(BaseAgent):
    def __init__(self, name: str = "Research Agent"):
        super().__init__(name, capabilities=["web_search", "document_analysis"])

    def perform_task(self, task_context: dict) -> dict:
        topic = task_context.get("topic", task_context.get("title", "unknown topic"))
        keywords = task_context.get("keywords", "").split(",")
        depth = task_context.get("depth", "overview")

        self.report_status(f"Starting research on '{topic}' with depth '{depth}'...")
        self.report_status(f"Keywords: {', '.join(keywords)}")

        # Simulate research activity
        time.sleep(random.uniform(2, 5))

        # Simulate findings
        findings = [
            f"Found key paper on {topic} by Author A (2023).",
            f"Relevant data set discovered at Source B.",
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
