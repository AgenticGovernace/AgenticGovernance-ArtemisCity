"""Dependency-free reference metrics for summarization experiments."""

from __future__ import annotations

import re
from collections import Counter
from statistics import fmean

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text)]


def _f1(overlap: int, predicted: int, reference: int) -> tuple[float, float, float]:
    precision = overlap / predicted if predicted else 0.0
    recall = overlap / reference if reference else 0.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, score


def _lcs_length(left: list[str], right: list[str]) -> int:
    """Calculate LCS length using one dynamic-programming row."""
    if len(right) > len(left):
        left, right = right, left
    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def evaluate_summary(generated: str, reference: str, source: str) -> dict[str, float]:
    """Return lightweight ROUGE-style overlap and compression metrics.

    This intentionally avoids adding a model/download dependency to the base
    experiment. Scores use Unicode word tokens, case folding, and no stemming.
    """
    generated_tokens = _tokens(generated)
    reference_tokens = _tokens(reference)
    source_tokens = _tokens(source)

    overlap = sum((Counter(generated_tokens) & Counter(reference_tokens)).values())
    rouge1_precision, rouge1_recall, rouge1_f1 = _f1(
        overlap,
        len(generated_tokens),
        len(reference_tokens),
    )
    lcs = _lcs_length(generated_tokens, reference_tokens)
    _, _, rouge_l_f1 = _f1(lcs, len(generated_tokens), len(reference_tokens))

    return {
        "rouge1_precision": rouge1_precision,
        "rouge1_recall": rouge1_recall,
        "rouge1_f1": rouge1_f1,
        "rouge_l_f1": rouge_l_f1,
        "compression_ratio": (
            len(generated_tokens) / len(source_tokens) if source_tokens else 0.0
        ),
        "generated_tokens": float(len(generated_tokens)),
        "reference_tokens": float(len(reference_tokens)),
        "source_tokens": float(len(source_tokens)),
    }


def aggregate_metrics(items: list[dict[str, float]]) -> dict[str, float]:
    """Average numeric metrics across evaluated records."""
    if not items:
        return {}
    keys = sorted(set().union(*(item.keys() for item in items)))
    return {key: fmean(item[key] for item in items if key in item) for key in keys}
