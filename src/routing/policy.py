"""Versioned execution-domain policy for Routing Kernel intent resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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

        if not isinstance(raw, dict):
            raise TypeError("intent policy must be a mapping")
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

        fallback_capability = fallback.get("capability")
        allowed_pairs = fallback.get("allowed_pairs")
        if not isinstance(fallback_capability, str) or not fallback_capability:
            raise ValueError("intent policy fallback requires a capability")
        if not isinstance(allowed_pairs, list):
            raise TypeError("intent policy fallback requires allowed_pairs")
        fallback_pairs = frozenset(
            (pair[0], pair[1])
            for pair in allowed_pairs
            if isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(value, str) and value for value in pair)
        )
        if len(fallback_pairs) != len(allowed_pairs):
            raise ValueError(
                "intent policy fallback pairs must contain mode/action strings"
            )

        version = raw.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError("intent policy requires a version")
        return cls(version, normalized_pairs, fallback_capability, fallback_pairs)

    def domain_for(self, mode: str, action_type: str) -> tuple[str, ...] | None:
        """Return the allowed capability domain for one declared ATP pair."""
        return self.pairs.get(mode, {}).get(action_type)

    def default_for(self, domain: tuple[str, ...]) -> str:
        """Choose the reviewed default without expanding the supplied domain."""
        if self.fallback_capability in domain:
            return self.fallback_capability
        return domain[0]
