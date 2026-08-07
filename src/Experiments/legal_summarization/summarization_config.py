"""Parameterized configuration for legal judgment summarization runs.

Supports:
- Summarization mode (abstractive via LLM, extractive via truncation)
- Target language subset (en, ur, sd)
- Output constraints (max length, style, audience)
- Prompt templating for different summarization strategies
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

DEFAULT_LEGAL_SUMMARY_TOKENS = 2048


class SummarizationMode(str, Enum):
    """How the summary is produced."""

    ABSTRACTIVE = "abstractive"  # LLM-generated
    EXTRACTIVE = "extractive"  # Leading-sentence / keyword extraction


class AggregationLevel(str, Enum):
    """Granularity of summarization."""

    SINGLE = "single"  # One summary per judgment
    BATCH = "batch"  # Aggregated summary across a group of judgments


class AudienceLevel(str, Enum):
    """Target audience for the summary."""

    LEGAL_PROFESSIONAL = "legal_professional"
    GENERAL_PUBLIC = "general_public"
    ACADEMIC = "academic"


@dataclass
class SummarizationConfig:
    """Immutable run configuration for a summarization batch.

    Attributes:
        dataset_config: Historical field name for the optional task-column
            filter (for example ``summary_en``). The loader separately owns
            the Hub repository's named dataset configuration.
        mode: Abstractive (LLM) or extractive.
        aggregation: Single-judgment or batch-aggregated summaries.
        audience: Target audience — controls prompt tone and detail.
        max_summary_tokens: Soft ceiling on summary length sent to the model.
        temperature: Sampling temperature for the LLM.
        system_prompt_override: Replace the default system prompt entirely.
        custom_user_prompt: Additional user-level instructions appended to
            every summarization prompt.
        split: Dataset split to process (``train``, ``validation``, ``test``).
        limit: Max number of records to process (``None`` = all).
        batch_tag: Free-form tag stored alongside results for filtering.
    """

    dataset_config: str = "summary_en"
    mode: SummarizationMode = SummarizationMode.ABSTRACTIVE
    aggregation: AggregationLevel = AggregationLevel.SINGLE
    audience: AudienceLevel = AudienceLevel.LEGAL_PROFESSIONAL
    # Historical successful runs produced roughly 500-560 final-answer
    # tokens. Reasoning models also consume output budget before emitting that
    # answer, so 2048 leaves room for both phases without permitting runaway
    # legal summaries.
    max_summary_tokens: int = DEFAULT_LEGAL_SUMMARY_TOKENS
    temperature: float = 0.7
    system_prompt_override: Optional[str] = None
    custom_user_prompt: Optional[str] = None
    split: str = "train"
    limit: Optional[int] = None
    batch_tag: str = "apollo"

    # ---- Prompt construction ------------------------------------------------

    _SYSTEM_PROMPTS: dict[str, str] = field(
        default_factory=dict, repr=False, init=False
    )

    def __post_init__(self) -> None:
        self._SYSTEM_PROMPTS = {
            AudienceLevel.LEGAL_PROFESSIONAL: (
                "You are an expert legal analyst. Produce a precise, "
                "citation-aware summary of the following court judgment. "
                "Preserve party names, statutory references, and the ratio decidendi."
            ),
            AudienceLevel.GENERAL_PUBLIC: (
                "You are a helpful legal assistant writing for a general audience. "
                "Summarize the following court judgment in plain language, "
                "avoiding jargon. Highlight the key outcome and its practical impact."
            ),
            AudienceLevel.ACADEMIC: (
                "You are an academic researcher in law. Provide a structured summary "
                "of the following court judgment, noting the legal question, "
                "arguments of each party, the court's reasoning, and the precedent set."
            ),
        }

    @property
    def system_prompt(self) -> str:
        """System prompt.

        Returns:
            str: String result produced by the operation.
        """
        if self.system_prompt_override:
            return self.system_prompt_override
        return self._SYSTEM_PROMPTS.get(
            self.audience,
            self._SYSTEM_PROMPTS[AudienceLevel.LEGAL_PROFESSIONAL],
        )

    def build_user_prompt(self, judgment_text: str) -> str:
        """Build the user-role message for a single judgment.

        Args:
            judgment_text (str): Legal judgment text to summarize.

        Returns:
            str: String result produced by the operation.
        """
        length_hint = f" Keep the summary under {self.max_summary_tokens} tokens."
        parts = [
            f"Summarize the following legal judgment.{length_hint}",
        ]
        if self.custom_user_prompt:
            parts.append(self.custom_user_prompt)
        parts.append(f"\n---\n{judgment_text}\n---")
        return "\n\n".join(parts)

    def build_batch_prompt(self, judgment_texts: list[str]) -> str:
        """Build a prompt that asks the model to synthesize across multiple judgments.

        Args:
            judgment_texts (list[str]): Collection of judgment texts to summarize together.

        Returns:
            str: String result produced by the operation.
        """
        separator = "\n\n===\n\n"
        combined = separator.join(
            f"[Judgment {i + 1}]\n{t}" for i, t in enumerate(judgment_texts)
        )
        length_hint = (
            f" Keep the combined summary under {self.max_summary_tokens} tokens."
        )
        parts = [
            f"Synthesize the following {len(judgment_texts)} legal judgments "
            f"into a single consolidated summary.{length_hint}",
        ]
        if self.custom_user_prompt:
            parts.append(self.custom_user_prompt)
        parts.append(f"\n---\n{combined}\n---")
        return "\n\n".join(parts)

    # ---- Serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """To dict.

        Returns:
            dict: Dictionary containing the resulting data.
        """
        d = asdict(self)
        d.pop("_SYSTEM_PROMPTS", None)
        d["mode"] = self.mode.value
        d["aggregation"] = self.aggregation.value
        d["audience"] = self.audience.value
        return d

    def to_json(self) -> str:
        """To json.

        Returns:
            str: String result produced by the operation.
        """
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> SummarizationConfig:
        """From dict.

        Args:
            data (dict): Structured data payload to transform or persist.

        Returns:
            SummarizationConfig: Resulting SummarizationConfig value produced by the operation.
        """
        data = dict(data)
        data.pop("_SYSTEM_PROMPTS", None)
        if "mode" in data:
            data["mode"] = SummarizationMode(data["mode"])
        if "aggregation" in data:
            data["aggregation"] = AggregationLevel(data["aggregation"])
        if "audience" in data:
            data["audience"] = AudienceLevel(data["audience"])
        return cls(**data)
