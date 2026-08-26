"""Legal summarization adapter built on Artemis City's live Exo agent stack."""

from __future__ import annotations

import re

from src.agents.base_agent import BaseAgent
from src.agents.llm_agent import LLMAgent

from .summarization_config import SummarizationConfig, SummarizationMode

MIN_LEGAL_SUMMARY_WORDS = 8


class LegalSummarizerAgent(BaseAgent):
    """Evaluate legal summarization without mutating production routing state.

    The experiment deliberately calls the same :class:`LLMAgent` used by the
    production Summarizer Agent, but does not register benchmark outcomes as
    live Hebbian/trust evidence. Experiment results have their own RunStore.
    """

    def __init__(
        self,
        name: str = "Legal Summarizer Agent",
        llm_agent: LLMAgent | None = None,
    ) -> None:
        super().__init__(
            name,
            capabilities=["legal_summarization", "text_summarization"],
        )
        self.llm_agent = llm_agent or LLMAgent()

    def get_sandbox_policies(self) -> list:
        return self.llm_agent.get_sandbox_policies()

    def get_sandbox_actions(self, task_context: dict) -> list[dict]:
        config = self._config(task_context)
        if config.mode == SummarizationMode.EXTRACTIVE:
            return []
        return self.llm_agent.get_sandbox_actions(task_context)

    def perform_task(self, task_context: dict) -> dict:
        config = self._config(task_context)
        judgments = task_context.get("judgments")
        if judgments:
            texts = [str(text).strip() for text in judgments if str(text).strip()]
            source_text = "\n\n".join(texts)
            prompt = config.build_batch_prompt(texts)
        else:
            source_text = str(task_context.get("content") or "").strip()
            prompt = config.build_user_prompt(source_text)

        if not source_text:
            return {
                "status": "failed",
                "summary": "No legal judgment text was provided.",
                "mode": config.mode.value,
            }

        if config.mode == SummarizationMode.EXTRACTIVE:
            summary = self._extractive_summary(
                source_text,
                max_words=config.max_summary_tokens,
            )
            return {
                "status": "success",
                "summary": summary,
                "mode": config.mode.value,
                "provider": "extractive_baseline",
            }

        result = self.llm_agent.perform_task(
            {
                "task_id": task_context.get("task_id"),
                "system_prompt": config.system_prompt,
                "prompt": prompt,
                "temperature": config.temperature,
                "max_tokens": config.max_summary_tokens,
                "model": task_context.get("model"),
                "model_url": task_context.get("model_url"),
            }
        )
        generated = str(result.get("summary") or "").strip()
        if (
            result.get("status") == "success"
            and len(generated.split()) < MIN_LEGAL_SUMMARY_WORDS
        ):
            return {
                **result,
                "status": "failed",
                "summary": "Model returned an unusably short legal summary.",
                "error": generated or "empty model summary",
                "mode": config.mode.value,
                "outcome_class": "provider_failure",
                "learning_eligible": False,
            }
        return {
            **result,
            "mode": config.mode.value,
        }

    @staticmethod
    def _config(task_context: dict) -> SummarizationConfig:
        config = task_context.get("summarization_config")
        if isinstance(config, SummarizationConfig):
            return config
        if isinstance(config, dict):
            return SummarizationConfig.from_dict(config)
        return SummarizationConfig()

    @staticmethod
    def _extractive_summary(text: str, *, max_words: int) -> str:
        """Return a deterministic sentence-leading baseline."""
        sentences = re.split(r"(?<=[.!?۔؟])\s+", text.strip())
        selected: list[str] = []
        word_count = 0
        for sentence in sentences:
            words = sentence.split()
            if not words:
                continue
            remaining = max_words - word_count
            if remaining <= 0:
                break
            selected.append(" ".join(words[:remaining]))
            word_count += min(len(words), remaining)
        return " ".join(selected).strip()
