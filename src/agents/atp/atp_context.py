"""Live ATP context resolution for routing and execution.

The parser and validator describe an ATP message. This module turns that
description into a production task context without coupling the ATP package to
the orchestrator. Explicit caller capabilities always win; otherwise the ATP
action domain selects the capability used by the governed router.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .atp_models import ATPActionType, ATPMessage, ATPMode
from .atp_parser import ATPParser
from .atp_validator import ATPValidator


ACTION_CAPABILITIES = {
    ATPActionType.SUMMARIZE: "text_summarization",
    ATPActionType.SCAFFOLD: "text_generation",
    ATPActionType.REFLECT: "reasoning",
    ATPActionType.EXECUTE: "llm_chat",
}


def validation_to_dict(result) -> Dict[str, Any]:
    """Serialize an ATP validation result for task/API metadata."""
    return {
        "is_valid": result.is_valid,
        "valid": result.is_valid,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
        "suggestions": list(result.suggestions),
        "has_issues": result.has_issues,
    }


def infer_capability(
    message: ATPMessage,
    *,
    explicit_capability: Optional[str] = None,
    default_capability: str = "llm_chat",
) -> str:
    """Resolve the capability domain for one ATP message."""
    if explicit_capability and explicit_capability.strip():
        return explicit_capability.strip()

    target = (message.target_zone or "").lower()
    if "memory" in target:
        return "memory_inspection"
    if message.action_type == ATPActionType.SUMMARIZE:
        return "text_summarization"
    if message.action_type == ATPActionType.SCAFFOLD:
        return "text_generation"
    if message.action_type == ATPActionType.REFLECT:
        return "reasoning"
    if message.mode == ATPMode.SYNTHESIZE:
        return "text_summarization"
    if message.mode in (ATPMode.REVIEW, ATPMode.REFLECT):
        return "reasoning"
    return ACTION_CAPABILITIES.get(message.action_type, default_capability)


def resolve_task_context(
    task_context: Dict[str, Any],
    *,
    strict: bool = False,
    default_capability: str = "llm_chat",
) -> Dict[str, Any]:
    """Parse ATP headers and attach their routing/execution context.

    Non-ATP tasks are returned unchanged. For ATP tasks, the agent receives
    clean content plus the structured header, and Hebbian learning is scoped by
    both action domain and resolved capability.
    """
    resolved = dict(task_context)
    raw_input = resolved.get("content") or resolved.get("context") or ""
    if not isinstance(raw_input, str) or not raw_input.strip():
        return resolved

    message, metrics = ATPParser().parse_with_metrics(raw_input)
    if not message.has_atp_headers:
        return resolved

    validation = ATPValidator(strict=strict).validate(message)
    if not validation.is_valid:
        detail = "; ".join(validation.errors) or "ATP validation failed"
        raise ValueError(detail)

    explicit = bool(
        resolved.get("required_capability")
        and resolved.get("_capability_explicit", True)
    )
    capability = infer_capability(
        message,
        explicit_capability=(
            str(resolved["required_capability"]) if explicit else None
        ),
        default_capability=default_capability,
    )
    action_domain = message.action_type.value.lower()
    if message.action_type == ATPActionType.UNKNOWN:
        action_domain = "unspecified"

    resolved.update(
        {
            "required_capability": capability,
            "routing_scope": f"atp:{action_domain}:{capability}",
            "atp_action_type": message.action_type.value,
            "atp": message.to_dict(),
            "atp_validation": validation_to_dict(validation),
            "atp_metrics": metrics,
            "atp_raw": raw_input,
        }
    )
    if message.content:
        resolved["content"] = message.content
        resolved["context"] = message.context or message.content
    return resolved

