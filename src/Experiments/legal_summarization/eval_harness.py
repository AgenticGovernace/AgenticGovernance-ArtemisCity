"""Automatic evaluation harness and grading system for legal summarization experiments.

Provides multi-dimensional rubric grading (legal structure, faithfulness/entity-verification,
conciseness, audience suitability, and reference alignment) along with letter grades,
pass/fail verdicts, and actionable review feedback.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .evaluation import evaluate_summary
from .summarization_config import AudienceLevel, SummarizationConfig

_LEGAL_ELEMENT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "facts_and_procedural_history": [
        re.compile(
            r"\b(fact|facts|procedural|history|background|appellant|respondent|petitioner)\b",
            re.I,
        ),
        re.compile(
            r"\b(plaintiff|defendant|prosecution|accused|alleged|claim)\b", re.I
        ),
    ],
    "legal_issues": [
        re.compile(
            r"\b(issue|question|whether|determined|controversy|dispute|argued)\b", re.I
        ),
        re.compile(r"\b(point|law|validity|constitutionality|jurisdiction)\b", re.I),
    ],
    "holding_and_ratio": [
        re.compile(
            r"\b(held|holding|ratio|reasoning|court\s+found|observed|concluded|ruled)\b",
            re.I,
        ),
        re.compile(r"\b(opinion|precedent|statute|interpretation|merit)\b", re.I),
    ],
    "disposition_and_order": [
        re.compile(
            r"\b(disposed|dismissed|allowed|remanded|ordered|held\s+that|decreed|judgment)\b",
            re.I,
        ),
        re.compile(r"\b(conviction|sentence|acquitted|relief|impugned)\b", re.I),
    ],
}

_LEGAL_CITATION_PATTERN = re.compile(
    r"\b(\d+\s+[A-Z]{2,10}\s+\d+|Section\s+\d+|Art(icle)?\.\s*\d+|Act,\s*\d{4}|P\.?L\.?D\.?|S\.?C\.?M\.?R\.?|AIR\s+\d{4})\b",
    re.I,
)
_NUMERIC_ENTITY_PATTERN = re.compile(r"\b\d+([.,]\d+)?\b")


@dataclass
class EvalResult:
    """Structured evaluation outcome for a single legal summary."""

    overall_score: float
    grade: str
    passed: bool
    criterion_scores: dict[str, float]
    review: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return dict representation of evaluation result."""
        return asdict(self)


class LegalEvalHarness:
    """Automatic evaluation harness for legal judgment summaries."""

    def __init__(self, pass_threshold: float = 70.0) -> None:
        self.pass_threshold = pass_threshold

    def evaluate_record(
        self,
        generated_summary: str,
        source_text: str,
        reference_summary: Optional[str] = None,
        config: Optional[SummarizationConfig] = None,
    ) -> EvalResult:
        """Perform automatic grading and generate structured review feedback.

        Args:
            generated_summary (str): The generated legal summary.
            source_text (str): The original legal judgment source text.
            reference_summary (Optional[str]): Optional ground-truth summary.
            config (Optional[SummarizationConfig]): Active summarization config.

        Returns:
            EvalResult: Multi-aspect evaluation metrics, letter grade, and review.
        """
        audience = (
            config.audience.value
            if config and hasattr(config.audience, "value")
            else AudienceLevel.LEGAL_PROFESSIONAL.value
        )

        # 1. Evaluate baseline quantitative metrics if reference is available
        ref_metrics = (
            evaluate_summary(generated_summary, reference_summary, source_text)
            if reference_summary
            else {}
        )

        # 2. Criterion scoring
        structure_score, missing_elements = self._score_legal_structure(
            generated_summary
        )
        faithfulness_score, entity_issues = self._score_faithfulness(
            generated_summary, source_text
        )
        conciseness_score = self._score_conciseness(generated_summary, source_text)
        audience_score = self._score_audience_suitability(generated_summary, audience)
        reference_score = self._score_reference_alignment(ref_metrics)

        criterion_scores = {
            "legal_structure": round(structure_score, 2),
            "faithfulness": round(faithfulness_score, 2),
            "conciseness": round(conciseness_score, 2),
            "audience_suitability": round(audience_score, 2),
        }
        if reference_summary:
            criterion_scores["reference_alignment"] = round(reference_score, 2)

        # 3. Overall Weighted Score (0 - 100)
        if reference_summary:
            overall_score = (
                structure_score * 0.25
                + faithfulness_score * 0.30
                + conciseness_score * 0.15
                + audience_score * 0.10
                + reference_score * 0.20
            )
        else:
            overall_score = (
                structure_score * 0.35
                + faithfulness_score * 0.35
                + conciseness_score * 0.15
                + audience_score * 0.15
            )

        overall_score = round(max(0.0, min(100.0, overall_score)), 2)
        grade = self._assign_letter_grade(overall_score)
        passed = overall_score >= self.pass_threshold

        # 4. Synthesize Review Feedback
        strengths: list[str] = []
        weaknesses: list[str] = []
        recommendations: list[str] = []

        if structure_score >= 80:
            strengths.append(
                "Contains key legal judgment components (facts, holding, disposition)."
            )
        else:
            weaknesses.append(
                f"Missing core legal structural elements: {', '.join(missing_elements)}."
            )
            recommendations.append(
                "Ensure the summary explicitly states the core issue, legal ratio, and court order."
            )

        if faithfulness_score >= 85:
            strengths.append(
                "High factual & entity consistency with the source judgment."
            )
        else:
            weaknesses.append(
                "Potential unverified entity or citation mentions detected."
            )
            if entity_issues:
                weaknesses.extend(entity_issues[:2])
            recommendations.append(
                "Double-check dates, statutory section numbers, and party names against source text."
            )

        if conciseness_score >= 80:
            strengths.append("Optimal compression ratio and informative brevity.")
        elif conciseness_score < 50:
            weaknesses.append(
                "Summary length is either overly verbose or excessively brief."
            )
            recommendations.append(
                "Adjust summary length to capture key holdings without copying full paragraphs."
            )

        if audience_score >= 80:
            strengths.append(
                f"Well-adapted tone and depth for target audience ({audience})."
            )
        else:
            weaknesses.append(
                f"Stylistic tone or terminology may not suit target audience ({audience})."
            )

        if reference_summary and reference_score >= 80:
            strengths.append(
                "Strong semantic overlap with reference summary (high ROUGE-1/ROUGE-L)."
            )

        review = {
            "verdict": "PASS" if passed else "FAIL",
            "overall_score": overall_score,
            "grade": grade,
            "audience": audience,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "missing_elements": missing_elements,
            "recommendations": recommendations,
            "reference_metrics": ref_metrics,
        }

        return EvalResult(
            overall_score=overall_score,
            grade=grade,
            passed=passed,
            criterion_scores=criterion_scores,
            review=review,
        )

    # ------------------------------------------------------------------
    # Criterion Evaluators
    # ------------------------------------------------------------------

    @staticmethod
    def _score_legal_structure(text: str) -> tuple[float, list[str]]:
        """Score presence of key legal components (0 - 100)."""
        if not text or not text.strip():
            return 0.0, list(_LEGAL_ELEMENT_PATTERNS.keys())

        matched_components = 0
        missing = []
        for component, patterns in _LEGAL_ELEMENT_PATTERNS.items():
            if any(pattern.search(text) for pattern in patterns):
                matched_components += 1
            else:
                missing.append(component)

        score = (matched_components / len(_LEGAL_ELEMENT_PATTERNS)) * 100.0
        return score, missing

    @staticmethod
    def _score_faithfulness(summary: str, source: str) -> tuple[float, list[str]]:
        """Verify statutory citations and numbers in summary exist in source."""
        if not summary.strip():
            return 0.0, ["Empty summary"]
        if not source.strip():
            return 100.0, []

        source_lower = source.lower()
        issues: list[str] = []

        # Check citations
        sum_citations = set(_LEGAL_CITATION_PATTERN.findall(summary))
        unsupported_citations = [
            cit[0] if isinstance(cit, tuple) else cit
            for cit in sum_citations
            if (cit[0] if isinstance(cit, tuple) else cit).lower() not in source_lower
        ]

        # Check numbers / dates
        sum_numbers = set(_NUMERIC_ENTITY_PATTERN.findall(summary))
        source_numbers = set(_NUMERIC_ENTITY_PATTERN.findall(source))
        unsupported_numbers = [
            num[0] if isinstance(num, tuple) else num
            for num in sum_numbers
            if num not in source_numbers
        ]

        total_entities = len(sum_citations) + len(sum_numbers)
        unsupported_total = len(unsupported_citations) + len(unsupported_numbers)

        if unsupported_citations:
            issues.append(
                f"Unverified citations in summary: {', '.join(unsupported_citations[:3])}"
            )
        if unsupported_numbers:
            issues.append(
                f"Unverified numerical entities in summary: {', '.join(unsupported_numbers[:3])}"
            )

        if total_entities == 0:
            return 90.0, issues

        fidelity = max(0.0, (total_entities - unsupported_total) / total_entities)
        return fidelity * 100.0, issues

    @staticmethod
    def _score_conciseness(summary: str, source: str) -> float:
        """Score compression ratio appropriateness (0 - 100)."""
        sum_words = len(summary.split())
        src_words = len(source.split())

        if sum_words == 0:
            return 0.0
        if src_words == 0:
            return 100.0

        ratio = sum_words / src_words
        max_ideal = 0.70 if src_words < 100 else 0.35

        if 0.05 <= ratio <= max_ideal:
            return 100.0
        elif ratio < 0.05:
            return max(30.0, (ratio / 0.05) * 100.0)
        else:
            excess = ratio - max_ideal
            return max(20.0, 100.0 - (excess * 120.0))

    @staticmethod
    def _score_audience_suitability(summary: str, audience: str) -> float:
        """Score text formatting and tone against target audience."""
        words = summary.split()
        if not words:
            return 0.0

        avg_word_len = sum(len(w) for w in words) / len(words)

        if audience == AudienceLevel.GENERAL_PUBLIC.value:
            if avg_word_len <= 5.5:
                return 100.0
            return max(50.0, 100.0 - (avg_word_len - 5.5) * 15)
        elif audience == AudienceLevel.ACADEMIC.value:
            if avg_word_len >= 5.0:
                return 100.0
            return max(60.0, avg_word_len * 20)
        else:
            return 90.0

    @staticmethod
    def _score_reference_alignment(metrics: dict[str, float]) -> float:
        """Score reference alignment based on ROUGE metrics (0 - 100)."""
        if not metrics:
            return 70.0
        rouge1 = metrics.get("rouge1_f1", 0.0)
        rouge_l = metrics.get("rouge_l_f1", 0.0)
        combined = (rouge1 * 0.6 + rouge_l * 0.4) * 100.0
        return min(100.0, max(0.0, combined))

    @staticmethod
    def _assign_letter_grade(score: float) -> str:
        """Map score to standard academic letter grade."""
        if score >= 93.0:
            return "A+"
        if score >= 87.0:
            return "A"
        if score >= 80.0:
            return "B"
        if score >= 70.0:
            return "C"
        if score >= 60.0:
            return "D"
        return "F"
