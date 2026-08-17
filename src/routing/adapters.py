"""Production adapters binding Routing Kernel ports to live Artemis subsystems.

``src/routing`` defines its inputs as Protocols so the kernel can be unit-tested
without a registry, trust store, or sandbox. Those Protocols had no production
implementations, which left the eligibility and authorization gates unreachable
from a running orchestrator. This module supplies them.

Each adapter is deliberately thin and read-only. Eligibility filtering scans
every registered agent against a requested capability, so an adapter that
mutated governance state would penalize agents for the ordinary act of not
matching — see :class:`SandboxAdmissionPreflight` for the specific trap.
"""

from __future__ import annotations

from typing import Any, Iterable

from src.routing.eligibility import AgentEligibilityRecord

DEFAULT_TENANT_ID = "default"


def _clean_names(values: Iterable[Any]) -> frozenset[str]:
    """Return a frozenset of non-empty stripped names from any iterable."""
    cleaned: set[str] = set()
    for value in values or ():
        if isinstance(value, str) and value.strip():
            cleaned.add(value.strip())
    return frozenset(cleaned)


class RegistryAdmissionLookup:
    """Project the live agent registry into immutable admission records.

    The projection intersects two sources on purpose:

    * the **in-memory** registry, which is authoritative for "this agent class
      is actually loaded and dispatchable", and
    * the **persisted** admission facts (tenant grants, scope grants, status,
      composite score), which survive restarts.

    Rows persisted by past runs whose Python classes are no longer registered
    are excluded, matching the same rule ``GET /api/agents`` already applies.
    Routing to such a row would resolve to an agent the orchestrator cannot
    dispatch.
    """

    __slots__ = ("_registry", "_default_tenant_id")

    def __init__(
        self,
        registry: Any,
        *,
        default_tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        if not default_tenant_id or not default_tenant_id.strip():
            raise ValueError("default_tenant_id must be a non-empty string")
        self._registry = registry
        self._default_tenant_id = default_tenant_id.strip()

    def list_admission_records(self) -> tuple[AgentEligibilityRecord, ...]:
        """Return one immutable snapshot of all registry admission records."""
        loaded = {
            agent.name: agent
            for agent in self._registry.get_all_agents()
            if getattr(agent, "name", None)
        }
        if not loaded:
            return ()

        persisted = {
            str(record.get("name")): record
            for record in self._registry.store.list_admission_records()
        }

        records: list[AgentEligibilityRecord] = []
        for name in sorted(loaded):
            agent = loaded[name]
            row = persisted.get(name, {})

            # Declared capabilities come from the loaded class; the persisted
            # copy can lag behind a code change, and dispatch obeys the class.
            capabilities = _clean_names(getattr(agent, "capabilities", ()) or ())
            if not capabilities:
                continue

            # An empty persisted scope grant means "no narrowing configured",
            # not "narrowed to nothing" -- the eligibility gate intersects
            # capabilities with scopes, so an empty set would deny every agent
            # on an unmigrated database.
            scopes = _clean_names(row.get("scopes", ())) or capabilities
            tenant_ids = _clean_names(row.get("tenant_ids", ())) or frozenset(
                {self._default_tenant_id}
            )

            governance = self._registry.governance.get(name) or {}
            status = str(row.get("status") or governance.get("status") or "active")

            composite = row.get("composite_score")
            if composite is None:
                score = self._registry.scores.get(name)
                composite = score.composite_score if score is not None else 0.0
            try:
                composite_score = float(composite)
            except (TypeError, ValueError):
                composite_score = 0.0
            composite_score = max(0.0, min(1.0, composite_score))

            agent_uid = row.get("agent_uid")
            records.append(
                AgentEligibilityRecord(
                    agent_id=str(agent_uid).strip() if agent_uid else name,
                    name=name,
                    capabilities=capabilities,
                    tenant_ids=tenant_ids,
                    scopes=scopes,
                    status=status,
                    quarantined=status == "quarantined",
                    suspended=status == "suspended",
                    composite_score=composite_score,
                )
            )
        return tuple(records)


class TrustAdmissionLookup:
    """Expose current decay-adjusted trust in the shape eligibility expects.

    ``EligibilityFilter`` treats a raised exception or an out-of-range score as
    a denial, so this adapter does not invent a neutral value on failure: a
    trust store that cannot answer must not silently admit an agent.
    """

    __slots__ = ("_trust_interface",)

    def __init__(self, trust_interface: Any) -> None:
        self._trust_interface = trust_interface

    def score(self, agent_id: str) -> float:
        """Return the current trust score in the closed interval zero to one."""
        record = self._trust_interface.get_trust_score(agent_id)
        raw = getattr(record, "score", record)
        return float(raw)


class SandboxAdmissionPreflight:
    """Read-only sandbox admission that never records a governance violation.

    ``AgentSandbox.check_dispatch`` reports a missing capability through
    ``_deny``, which persists a violation and auto-quarantines on the third
    strike. Eligibility filtering asks about every registered agent, so routing
    admission through ``check_dispatch`` would quarantine agents for the
    ordinary act of not advertising the requested capability. This adapter
    therefore reproduces only the *read* half of the preflight: quarantine
    state and declared capability.
    """

    __slots__ = ("_registry",)

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def allows(
        self,
        agent_id: str,
        capabilities: frozenset[str],
        tenant_id: str,
    ) -> bool:
        """Return true only when dispatch can enter the candidate sandbox."""
        del tenant_id  # Tenant admission is enforced by the eligibility gate.
        if not capabilities:
            return False

        agent = self._registry.get_agent(agent_id)
        if agent is None:
            # ``agent_id`` may be a stable UID rather than the registry name.
            agent = next(
                (
                    candidate
                    for candidate in self._registry.get_all_agents()
                    if getattr(candidate, "name", None) == agent_id
                ),
                None,
            )
        if agent is None:
            return False

        if self._registry.is_quarantined(agent.name):
            return False

        declared = _clean_names(getattr(agent, "capabilities", ()) or ())
        return capabilities.issubset(declared)
