"""Shared policy helpers for transparent agent fallback behavior.

Production agents must never turn an unavailable model provider into an
unlabelled success.  Local baselines remain useful for demos and tests, but
they are opt-in and excluded from Hebbian/trust learning.
"""

from __future__ import annotations

import os
from typing import Any

_TRUE_VALUES = {"1", "true", "yes", "on"}


def synthetic_fallback_enabled(task_context: dict[str, Any]) -> bool:
    """Return whether a task explicitly permits a local synthetic baseline."""
    explicit = task_context.get("allow_synthetic_fallback")
    if isinstance(explicit, bool):
        return explicit
    return (
        os.getenv("ARTEMIS_SYNTHETIC_AGENT_FALLBACK", "0").strip().lower()
        in _TRUE_VALUES
    )


def delegate_failure(llm_result: dict[str, Any]) -> dict[str, Any]:
    """Copy safe, structured provider-failure details into a wrapper result."""
    fields = (
        "provider",
        "model",
        "model_url",
        "llm_error",
        "failure_kind",
        "retryable",
        "upstream_status_code",
        "attempt_count",
        "retry_after_seconds",
        "exo_request",
    )
    return {key: llm_result.get(key) for key in fields if key in llm_result}


def provider_failure_result(
    llm_result: dict[str, Any], *, agent_name: str
) -> dict[str, Any]:
    """Return an honest failed wrapper result for an unavailable provider."""
    failure = delegate_failure(llm_result)
    summary = str(
        llm_result.get("summary")
        or llm_result.get("error")
        or f"{agent_name} could not reach its configured model provider."
    )
    return {
        **failure,
        "status": "failed",
        "summary": summary,
        "error": summary,
        "provider": failure.get("provider", "exo"),
        "fallback_used": False,
        "outcome_class": "provider_failure",
        "learning_eligible": False,
        "delegate_failure": failure,
    }


def degraded_metadata(provider: str, reason: str) -> dict[str, Any]:
    """Return the common non-learning metadata for an intentional baseline."""
    return {
        "provider": provider,
        "fallback_used": True,
        "degraded": True,
        "degraded_reason": reason,
        "outcome_class": "degraded_success",
        "learning_eligible": False,
    }
