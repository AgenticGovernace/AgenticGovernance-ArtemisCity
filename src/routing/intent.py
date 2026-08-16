"""Authoritative ATP and trusted-adapter intent resolution."""

from __future__ import annotations

from pathlib import Path

from src.routing.contracts import (
    RequestedConstraintsV1,
    ResolvedIntentV1,
    TaskIntentV1,
)
from src.routing.policy import IntentPolicy


class IntentDenied(ValueError):
    """A stable routing-boundary denial suitable for callers and audit logs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class IntentResolver:
    """Resolve capability only from strict ATP or a trusted typed adapter."""

    def __init__(self, policy: IntentPolicy) -> None:
        self.policy = policy

    @classmethod
    def default(cls) -> IntentResolver:
        """Load the reviewed policy bundled with the routing source tree."""
        root = Path(__file__).resolve().parents[2]
        return cls(IntentPolicy.load(root / "config/routing/intent-policy.v1.yaml"))

    def resolve(
        self,
        content: str,
        typed_intent: TaskIntentV1 | None,
        requested: RequestedConstraintsV1,
    ) -> ResolvedIntentV1:
        """Return one policy-bounded intent or a stable denial."""
        from src.agents.atp.atp_parser import ATPParser
        from src.agents.atp.atp_validator import ATPValidator

        parser = ATPParser()
        message = parser.parse(content)
        if parser.is_atp_formatted(content):
            if typed_intent is not None:
                raise IntentDenied(
                    "ambiguous_intent_source",
                    "ATP headers and typed-adapter intent cannot be combined",
                )
            validation = ATPValidator(strict=True).validate(message)
            if not validation.is_valid:
                detail = "; ".join(validation.errors) or "ATP validation failed"
                raise IntentDenied("invalid_atp", detail)
            if not message.context or not message.context.strip():
                raise IntentDenied("invalid_atp", "ATP context is required")
            intent = TaskIntentV1(
                mode=message.mode.value,
                action_type=message.action_type.value,
                context=message.context,
                target_zone=message.target_zone or "unspecified",
                source="caller-atp",
            )
        else:
            if typed_intent is None:
                raise IntentDenied(
                    "missing_typed_intent",
                    "tasks without ATP headers require a trusted typed-adapter intent",
                )
            if typed_intent.source != "typed-adapter":
                raise IntentDenied(
                    "invalid_typed_intent",
                    "tasks without ATP headers require typed-adapter intent source",
                )
            intent = typed_intent

        domain = self.policy.domain_for(intent.mode, intent.action_type)
        if not domain:
            raise IntentDenied("invalid_atp", "ATP pair has no execution domain")
        requested_capability = requested.capability
        if requested_capability is not None and requested_capability not in domain:
            raise IntentDenied(
                "capability_domain_conflict",
                "requested capability expands the ATP-authorized domain",
            )
        selected = requested_capability or self.policy.default_for(domain)
        return ResolvedIntentV1(**intent.model_dump(), capability=selected)
