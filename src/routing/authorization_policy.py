"""Reviewed target-zone and Artemis capability policy for authorization.

``ArtemisAuthorizer`` depends on the ``AuthorizationCapabilityPolicy`` port to
supply the two outermost bounds of the effective capability intersection: what
the requested target zone permits, and what Artemis itself is willing to route.
This module is the production implementation of that port, loaded from a
reviewed YAML document rather than hard-coded, so operators can tighten policy
without a code change.

Zone rules are ordered and first-match-wins because ATP target zones are
free-form path-like strings (``/Projects/Artemis``), not a closed enum.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.routing.contracts import ResolvedIntentV1

_POLICY_VERSION = "artemis.authorization-policy/1"

DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "config/routing/authorization-policy.v1.yaml"
)


class AuthorizationPolicyError(ValueError):
    """The reviewed authorization policy document is absent or malformed."""


@dataclass(frozen=True, slots=True)
class ZoneRule:
    """One ordered fnmatch rule binding a target-zone pattern to capabilities."""

    pattern: str
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class ReviewedCapabilityPolicy:
    """Current target-zone and Artemis capability policy loaded from disk."""

    version: str
    artemis_capabilities: frozenset[str]
    zones: tuple[ZoneRule, ...]

    @classmethod
    def load(cls, path: str | Path | None = None) -> ReviewedCapabilityPolicy:
        """Load and validate one reviewed authorization policy document."""
        policy_path = Path(path) if path is not None else DEFAULT_POLICY_PATH
        try:
            with policy_path.open(encoding="utf-8") as policy_file:
                raw: Any = yaml.safe_load(policy_file)
        except OSError as error:
            raise AuthorizationPolicyError(
                "authorization policy document is unreadable"
            ) from error
        except yaml.YAMLError as error:
            raise AuthorizationPolicyError(
                "authorization policy document is not valid YAML"
            ) from error

        if not isinstance(raw, dict) or set(raw) != {
            "version",
            "artemis_capabilities",
            "zones",
        }:
            raise AuthorizationPolicyError(
                "authorization policy must use the reviewed V1 document shape"
            )
        if raw["version"] != _POLICY_VERSION:
            raise AuthorizationPolicyError(
                "authorization policy version is not reviewed"
            )

        artemis_capabilities = cls._capability_set(
            raw["artemis_capabilities"], "artemis_capabilities"
        )

        zones_raw = raw["zones"]
        if not isinstance(zones_raw, list) or not zones_raw:
            raise AuthorizationPolicyError(
                "authorization policy requires at least one zone rule"
            )
        zones: list[ZoneRule] = []
        for entry in zones_raw:
            if not isinstance(entry, dict) or set(entry) != {
                "pattern",
                "capabilities",
            }:
                raise AuthorizationPolicyError(
                    "each zone rule requires exactly a pattern and capabilities"
                )
            pattern = entry["pattern"]
            if not isinstance(pattern, str) or not pattern.strip():
                raise AuthorizationPolicyError(
                    "zone rule pattern must be a non-empty string"
                )
            zones.append(
                ZoneRule(
                    pattern=pattern.strip(),
                    capabilities=cls._capability_set(
                        entry["capabilities"], "zone capabilities"
                    ),
                )
            )
        return cls(_POLICY_VERSION, artemis_capabilities, tuple(zones))

    @staticmethod
    def _capability_set(values: Any, label: str) -> frozenset[str]:
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value.strip() for value in values)
        ):
            raise AuthorizationPolicyError(
                f"{label} must be a non-empty list of capability names"
            )
        return frozenset(value.strip() for value in values)

    # -- AuthorizationCapabilityPolicy port ---------------------------------

    def target_zone_capabilities(self, target_zone: str) -> frozenset[str]:
        """Return current capabilities permitted in one target zone."""
        if not isinstance(target_zone, str) or not target_zone.strip():
            raise AuthorizationPolicyError("target zone must be a non-empty string")
        candidate = target_zone.strip()
        for rule in self.zones:
            if fnmatch.fnmatch(candidate, rule.pattern):
                return rule.capabilities
        # No trailing catch-all was configured: deny rather than widen.
        return frozenset()

    def artemis_capabilities_for(self, intent: ResolvedIntentV1) -> frozenset[str]:
        """Return current Artemis capabilities permitted for this intent."""
        del intent  # Artemis policy is currently intent-independent.
        return self.artemis_capabilities


class CapabilityPolicyAdapter:
    """Bind a reviewed policy to the exact ``AuthorizationCapabilityPolicy`` shape.

    ``ReviewedCapabilityPolicy`` stores ``artemis_capabilities`` as data, but the
    port requires a method of that name. This thin adapter resolves the collision
    without forcing the policy document to rename a reviewed field.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: ReviewedCapabilityPolicy) -> None:
        self._policy = policy

    @classmethod
    def load(cls, path: str | Path | None = None) -> CapabilityPolicyAdapter:
        """Load the reviewed document and wrap it in the port shape."""
        return cls(ReviewedCapabilityPolicy.load(path))

    @property
    def policy(self) -> ReviewedCapabilityPolicy:
        """Return the underlying reviewed policy."""
        return self._policy

    def target_zone_capabilities(self, target_zone: str) -> frozenset[str]:
        """Return current capabilities permitted in one target zone."""
        return self._policy.target_zone_capabilities(target_zone)

    def artemis_capabilities(self, intent: ResolvedIntentV1) -> frozenset[str]:
        """Return current Artemis capabilities permitted for this intent."""
        return self._policy.artemis_capabilities_for(intent)
