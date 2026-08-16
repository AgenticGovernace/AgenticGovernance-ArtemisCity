from .base_agent import BaseAgent
import time


class SummarizerAgent(BaseAgent):
    def __init__(self, name: str = "Summarizer Agent"):
        super().__init__(name, capabilities=["text_summarization"])

    def perform_task(self, task_context: dict) -> dict:
        text_to_summarize = task_context.get("content", "")
        if not text_to_summarize:
            self.report_status("No content provided to summarize.")
            return {
                "status": "failed",
                "summary": "No content was provided for summarization.",
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
