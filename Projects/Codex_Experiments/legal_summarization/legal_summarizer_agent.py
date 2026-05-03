"""Legal Summarizer Agent — domain-specific summarization via EXO cluster.

Extends the framework's BaseAgent contract with legal-judgment prompts
driven by a ``SummarizationConfig``.  Falls back to extractive truncation
when EXO is unavailable (same pattern as the core SummarizerAgent).
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

# Support running both from repo root and from within Concept_Demos/
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
sys.path.insert(
    0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "Concept_Demos")
)

from Concept_Demos.src.agents.base_agent import BaseAgent
from Concept_Demos.src.mcp.exo_client import ExoClient

try:
    from .summarization_config import (
        AggregationLevel,
        SummarizationConfig,
        SummarizationMode,
    )
except ImportError:
    from summarization_config import (
        AggregationLevel,
        SummarizationConfig,
        SummarizationMode,
    )

logger = logging.getLogger("legal_summarization.agent")


class LegalSummarizerAgent(BaseAgent):
    """Agent that summarizes legal judgments using a configurable prompt pipeline.

    Capabilities registered: ``["legal_summarization"]``

    The agent reads its behaviour from a ``SummarizationConfig`` attached to
    the task context (key ``"summarization_config"``) or falls back to a
    default config.
    """

    def __init__(
        self,
        name: str = "Legal Summarizer Agent",
        exo_client: Optional[ExoClient] = None,
        default_config: Optional[SummarizationConfig] = None,
    ):
        super().__init__(
            name, capabilities=["legal_summarization", "text_summarization"]
        )
        self._exo = exo_client
        self._default_config = default_config or SummarizationConfig()

    # ------------------------------------------------------------------
    # EXO resolution (lazy, same pattern as core SummarizerAgent)
    # ------------------------------------------------------------------

    def _get_exo(self) -> Optional[ExoClient]:
        if self._exo is None:
            try:
                self._exo = ExoClient()
            except Exception:
                return None
        return self._exo if self._exo.is_available() else None

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def perform_task(self, task_context: dict) -> dict:
        """Summarize legal judgment text from ``task_context["content"]``.

        Extra context keys consumed:
            - ``summarization_config`` (dict or SummarizationConfig)
            - ``judgments`` (list[str]) — for batch/aggregated mode
        """
        config = self._resolve_config(task_context)

        # Batch aggregation path
        if config.aggregation == AggregationLevel.BATCH:
            texts = task_context.get("judgments", [])
            if not texts:
                texts = [task_context.get("content", "")]
            return self._summarize_batch(texts, config)

        # Single-judgment path
        text = task_context.get("content", "")
        if not text:
            self.report_status("No content provided to summarize.")
            return {"status": "failed", "summary": "No content provided."}

        return self._summarize_single(text, config)

    # ------------------------------------------------------------------
    # Single-judgment summarization
    # ------------------------------------------------------------------

    def _summarize_single(self, text: str, config: SummarizationConfig) -> dict:
        self.report_status(
            f"Summarizing judgment ({len(text)} chars, mode={config.mode.value}, "
            f"audience={config.audience.value})"
        )

        if config.mode == SummarizationMode.ABSTRACTIVE:
            exo = self._get_exo()
            if exo:
                return self._abstractive_via_exo(exo, text, config)
            self.report_status("EXO unavailable — falling back to extractive mode.")

        return self._extractive_fallback(text, config)

    def _abstractive_via_exo(
        self, exo: ExoClient, text: str, config: SummarizationConfig
    ) -> dict:
        messages = [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": config.build_user_prompt(text)},
        ]
        try:
            summary = exo.chat(
                messages,
                temperature=config.temperature,
                max_tokens=config.max_summary_tokens,
            )
        except Exception as exc:
            self.report_status(f"EXO inference failed ({exc}), extractive fallback.")
            return self._extractive_fallback(text, config)

        self.report_status("Abstractive summarization completed via EXO.")
        return {
            "status": "success",
            "mode": "abstractive",
            "original_length": len(text),
            "summary": summary,
            "summary_length": len(summary),
            "config": config.to_dict(),
        }

    def _extractive_fallback(self, text: str, config: SummarizationConfig) -> dict:
        """Simple leading-sentence extraction when no LLM is available."""
        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        target = max(3, min(len(sentences), config.max_summary_tokens // 40))
        summary = ". ".join(sentences[:target]) + "."
        self.report_status("Extractive summarization completed (fallback).")
        return {
            "status": "success",
            "mode": "extractive",
            "original_length": len(text),
            "summary": summary,
            "summary_length": len(summary),
            "config": config.to_dict(),
        }

    # ------------------------------------------------------------------
    # Batch / aggregated summarization
    # ------------------------------------------------------------------

    def _summarize_batch(self, texts: list[str], config: SummarizationConfig) -> dict:
        self.report_status(
            f"Aggregated summarization of {len(texts)} judgments "
            f"(mode={config.mode.value})"
        )

        if config.mode == SummarizationMode.ABSTRACTIVE:
            exo = self._get_exo()
            if exo:
                messages = [
                    {"role": "system", "content": config.system_prompt},
                    {"role": "user", "content": config.build_batch_prompt(texts)},
                ]
                try:
                    summary = exo.chat(
                        messages,
                        temperature=config.temperature,
                        max_tokens=config.max_summary_tokens,
                    )
                    self.report_status("Batch abstractive summarization completed.")
                    return {
                        "status": "success",
                        "mode": "abstractive_batch",
                        "judgment_count": len(texts),
                        "total_input_chars": sum(len(t) for t in texts),
                        "summary": summary,
                        "summary_length": len(summary),
                        "config": config.to_dict(),
                    }
                except Exception as exc:
                    self.report_status(f"Batch EXO inference failed ({exc}), fallback.")

        # Extractive fallback: concatenate leading sentences from each judgment
        parts = []
        for i, text in enumerate(texts):
            sentences = [
                s.strip() for s in text.replace("\n", " ").split(".") if s.strip()
            ]
            lead = ". ".join(sentences[:2]) + "." if sentences else "(empty)"
            parts.append(f"[{i + 1}] {lead}")
        summary = "\n".join(parts)

        self.report_status("Batch extractive summarization completed (fallback).")
        return {
            "status": "success",
            "mode": "extractive_batch",
            "judgment_count": len(texts),
            "total_input_chars": sum(len(t) for t in texts),
            "summary": summary,
            "summary_length": len(summary),
            "config": config.to_dict(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_config(task_context: dict) -> SummarizationConfig:
        raw = task_context.get("summarization_config")
        if raw is None:
            return SummarizationConfig()
        if isinstance(raw, SummarizationConfig):
            return raw
        if isinstance(raw, dict):
            return SummarizationConfig.from_dict(raw)
        return SummarizationConfig()
