"""Versioned execution-domain policy for Routing Kernel intent resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_POLICY_VERSION = "artemis.intent-policy/1"
_REVIEWED_PAIRS = {
    "Build": {"Scaffold": ("text_generation",), "Execute": ("llm_chat",)},
    "Review": {
        "Summarize": ("text_summarization",),
        "Reflect": ("reasoning",),
    },
    "Organize": {"Scaffold": ("text_generation",), "Execute": ("llm_chat",)},
    "Capture": {"Summarize": ("text_summarization",)},
    "Synthesize": {
        "Summarize": ("text_summarization",),
        "Reflect": ("reasoning",),
    },
    "Commit": {"Execute": ("llm_chat",)},
    "Reflect": {
        "Reflect": ("reasoning",),
        "Summarize": ("text_summarization",),
    },
}
_REVIEWED_FALLBACK_CAPABILITY = "llm_chat"
_REVIEWED_FALLBACK_PAIRS = (
    ("Build", "Execute"),
    ("Organize", "Execute"),
    ("Commit", "Execute"),
)


@dataclass(frozen=True)
class IntentPolicy:
    """The capability domains explicitly authorized for ATP mode/action pairs."""

    version: str
    pairs: dict[str, dict[str, tuple[str, ...]]]
    fallback_capability: str
    fallback_pairs: frozenset[tuple[str, str]]

    @classmethod
    def load(cls, path: str | Path) -> IntentPolicy:
        """Load one reviewed policy document from disk."""
        with Path(path).open(encoding="utf-8") as policy_file:
            raw: Any = yaml.safe_load(policy_file)

        if not isinstance(raw, dict) or set(raw) != {"version", "pairs", "fallback"}:
            raise ValueError("intent policy must use the reviewed V1 document shape")
        if raw["version"] != _POLICY_VERSION:
            raise ValueError("intent policy version is not reviewed")
        pairs = raw.get("pairs")
        fallback = raw.get("fallback")
        if not isinstance(pairs, dict) or not isinstance(fallback, dict):
            raise TypeError("intent policy requires pairs and fallback mappings")

        normalized_pairs: dict[str, dict[str, tuple[str, ...]]] = {}
        for mode, actions in pairs.items():
            if not isinstance(mode, str) or not isinstance(actions, dict):
                raise TypeError("intent policy pairs must map modes to actions")
            normalized_actions: dict[str, tuple[str, ...]] = {}
            for action, capabilities in actions.items():
                if (
                    not isinstance(action, str)
                    or not isinstance(capabilities, list)
                    or not capabilities
                    or not all(
                        isinstance(capability, str) and capability
                        for capability in capabilities
                    )
                ):
                    raise ValueError(
                        "intent policy domains must be non-empty capability lists"
                    )
                normalized_actions[action] = tuple(capabilities)
            normalized_pairs[mode] = normalized_actions

        if normalized_pairs != _REVIEWED_PAIRS:
            raise ValueError("intent policy pairs are not the reviewed V1 domains")
        if set(fallback) != {"capability", "allowed_pairs"}:
            raise ValueError("intent policy fallback must use the reviewed V1 shape")
        fallback_capability = fallback["capability"]
        allowed_pairs = fallback["allowed_pairs"]
        if fallback_capability != _REVIEWED_FALLBACK_CAPABILITY:
            raise ValueError("intent policy fallback capability is not reviewed")
        if not isinstance(allowed_pairs, list):
            raise TypeError("intent policy fallback requires allowed_pairs")
        parsed_fallback_pairs: list[tuple[str, str]] = []
        for pair in allowed_pairs:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(value, str) and value for value in pair)
            ):
                raise ValueError(
                    "intent policy fallback pairs must contain mode/action strings"
                )
            parsed_fallback_pairs.append((pair[0], pair[1]))
        if len(set(parsed_fallback_pairs)) != len(parsed_fallback_pairs):
            raise ValueError("intent policy fallback pairs must not be duplicated")
        if tuple(parsed_fallback_pairs) != _REVIEWED_FALLBACK_PAIRS:
            raise ValueError("intent policy fallback pairs are not reviewed")
        return cls(
            _POLICY_VERSION,
            normalized_pairs,
            fallback_capability,
            frozenset(parsed_fallback_pairs),
        )

    def domain_for(self, mode: str, action_type: str) -> tuple[str, ...] | None:
        """Return the allowed capability domain for one declared ATP pair."""
        return self.pairs.get(mode, {}).get(action_type)

    def default_for(self, domain: tuple[str, ...]) -> str:
        """Choose the reviewed default without expanding the supplied domain."""
        if self.fallback_capability in domain:
            return self.fallback_capability
        return domain[0]
