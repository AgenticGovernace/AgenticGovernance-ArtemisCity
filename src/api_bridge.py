"""JSON command bridge between the TypeScript API and the Python core.

The TypeScript Express layer (``app/api``) is the public HTTP boundary; it
shells out to this module to perform registry / governance operations against
the authoritative Python core, exchanging JSON over stdin/stdout.

Protocol
--------
Invoked as ``python -m src.api_bridge`` (cwd = repo root). Reads a single JSON
object from stdin of the form::

    {"command": "<namespace>.<action>", "payload": { ... }}

and writes a single JSON object to stdout::

    {"ok": true, "data": { ... }}            # success
    {"ok": false, "error": "...", "code": "..."}   # failure

The registry database path is taken from ``payload.db_path`` if present,
otherwise the ``ARTEMIS_REGISTRY_DB`` env var, otherwise the package default.
Keeping this stdlib-only (no web framework) means it runs in CI and is unit
testable directly via :func:`dispatch`.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Dict

from src.governance.approvals import SelfUpdateGovernor, UpdateProposal
from src.governance.trust import (
    TrustMetrics,
    compute_trust_score,
    trust_breakdown,
)
from src.integration.agent_registry import AgentRegistryStore


class BridgeError(Exception):
    """A command failure carrying a stable machine-readable code."""

    def __init__(self, message: str, code: str = "BRIDGE_ERROR"):
        super().__init__(message)
        self.code = code


def _resolve_db_path(payload: Dict[str, Any]) -> str:
    return (
        payload.get("db_path")
        or os.environ.get("ARTEMIS_REGISTRY_DB")
        or "data/agent_registry.db"
    )


def _store(payload: Dict[str, Any]) -> AgentRegistryStore:
    return AgentRegistryStore(db_path=_resolve_db_path(payload))


def _require(payload: Dict[str, Any], key: str) -> Any:
    if key not in payload or payload[key] in (None, ""):
        raise BridgeError(f"missing required field: {key}", code="INVALID_REQUEST")
    return payload[key]


# ---------------------------------------------------------------------------
# Command handlers — each takes the payload dict and returns a JSON-able dict
# ---------------------------------------------------------------------------


def _list_agents(payload: Dict[str, Any]) -> Dict[str, Any]:
    records = _store(payload).list_agent_records()
    return {"agents": records, "total": len(records)}


def _get_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "name")
    record = _store(payload).get_agent_record(name)
    if record is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    return record


def _get_violations(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "name")
    store = _store(payload)
    if store.get_agent_record(name) is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    include_cleared = bool(payload.get("include_cleared", False))
    raw_limit = payload.get("limit", 100)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise BridgeError(
            f"limit must be an integer, got {raw_limit!r}", code="INVALID_REQUEST"
        )
    if limit < 1:
        raise BridgeError("limit must be >= 1", code="INVALID_REQUEST")
    violations = store.get_violations(name, include_cleared, limit)
    state = store.get_governance_state(name) or {}
    return {
        "agent_name": name,
        "violation_count": state.get("violation_count", 0),
        "quarantined": state.get("status") == "quarantined",
        "violations": violations,
    }


def _clear_violations(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "name")
    store = _store(payload)
    if store.get_agent_record(name) is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    rationale = payload.get("rationale", "")
    override_tier = payload.get("override_tier")
    try:
        cleared = store.clear_violations(name, rationale, override_tier)
    except ValueError as exc:
        raise BridgeError(str(exc), code="INVALID_REQUEST")
    state = store.get_governance_state(name) or {}
    return {
        "agent_name": name,
        "cleared": cleared,
        "violation_count": state.get("violation_count", 0),
        "quarantined": state.get("status") == "quarantined",
        "trust_tier": state.get("trust_tier"),
    }


def _set_trust_tier(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "name")
    tier = _require(payload, "tier")
    store = _store(payload)
    if store.get_agent_record(name) is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    try:
        store.set_trust_tier(name, tier)
    except ValueError as exc:
        raise BridgeError(str(exc), code="INVALID_REQUEST")
    return store.get_governance_state(name) or {}


def _record_violation(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "name")
    vtype = _require(payload, "violation_type")
    details = payload.get("details", {})
    store = _store(payload)
    if store.get_agent_record(name) is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    try:
        return store.record_violation(name, vtype, details)
    except ValueError as exc:
        raise BridgeError(str(exc), code="INVALID_REQUEST")


def _build_metrics(payload: Dict[str, Any], store, name: str) -> TrustMetrics:
    """Construct TrustMetrics from a payload's ``metrics`` block, defaulting
    ``recent_violation_count`` to the agent's persisted count when absent."""
    metrics = dict(payload.get("metrics") or {})
    if "recent_violation_count" not in metrics:
        state = store.get_governance_state(name) or {}
        metrics["recent_violation_count"] = state.get("violation_count", 0) or 0
    # Drop unknown keys so a stray field can't crash the dataclass.
    allowed = TrustMetrics.__dataclass_fields__.keys()
    filtered = {k: v for k, v in metrics.items() if k in allowed}
    return TrustMetrics(**filtered)


def _compute_trust(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "name")
    store = _store(payload)
    if store.get_agent_record(name) is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    metrics = _build_metrics(payload, store, name)
    score = compute_trust_score(metrics)
    persist = payload.get("persist", True)
    if persist:
        store.set_trust_score(name, score)
    return {
        "agent_name": name,
        "trust_score": score,
        "persisted": bool(persist),
        "breakdown": trust_breakdown(metrics),
        "has_execution_history": metrics.has_execution_history,
    }


def _evaluate_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _require(payload, "agent_name")
    store = _store(payload)
    record = store.get_agent_record(name)
    if record is None:
        raise BridgeError(f"agent not found: {name}", code="NOT_FOUND")
    metrics_given = payload.get("metrics") is not None
    has_history = bool(payload.get("has_history", True))

    # Resolve the trust score: explicit > computed-from-metrics > persisted.
    if "trust_score" in payload and payload["trust_score"] is not None:
        trust_score = float(payload["trust_score"])
        if not 0.0 <= trust_score <= 1.0:
            raise BridgeError("trust_score must be between 0 and 1", code="INVALID_REQUEST")
    elif metrics_given:
        metrics = _build_metrics(payload, store, name)
        trust_score = compute_trust_score(metrics)
        has_history = metrics.has_execution_history
    else:
        trust_score = record.get("trust_score")
        if trust_score is None:
            raise BridgeError(
                "no trust_score available; provide trust_score or metrics",
                code="INVALID_REQUEST",
            )

    proposal = UpdateProposal(
        agent_name=name,
        code_change_ratio=float(payload.get("code_change_ratio", 0.0)),
        breaking_changes=bool(payload.get("breaking_changes", False)),
        new_dependencies=bool(payload.get("new_dependencies", False)),
        policy_change=bool(payload.get("policy_change", False)),
        affects_governance=bool(payload.get("affects_governance", False)),
    )
    decision = SelfUpdateGovernor().classify(proposal, trust_score, has_history)
    result = decision.to_dict()
    result["trust_score"] = trust_score
    return result


COMMANDS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "registry.list_agents": _list_agents,
    "registry.get_agent": _get_agent,
    "registry.get_violations": _get_violations,
    "registry.clear_violations": _clear_violations,
    "registry.set_trust_tier": _set_trust_tier,
    "registry.record_violation": _record_violation,
    "governance.compute_trust": _compute_trust,
    "governance.evaluate_update": _evaluate_update,
}


def dispatch(command: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Run a bridge command and return its JSON-able result dict.
    
    Raises :class:`BridgeError` for unknown commands or handler failures.
    
    Args:
        command (str): Command text to process.
        payload (Dict[str, Any] | None): Request payload passed through the bridge or API
            layer.
    
    Returns:
        Dict[str, Any]: Dictionary containing the resulting data.
    """
    handler = COMMANDS.get(command)
    if handler is None:
        raise BridgeError(f"unknown command: {command}", code="UNKNOWN_COMMAND")
    return handler(payload or {})


def main(argv=None) -> int:
    """CLI entry point: read one JSON request from stdin, write one to stdout.
    
    Args:
        argv: Argv value used by this operation.
    
    Returns:
        int: Integer result produced by the operation.
    """
    raw = sys.stdin.read()
    try:
        request = json.loads(raw) if raw.strip() else {}
        command = request.get("command")
        if not command:
            raise BridgeError("missing 'command'", code="INVALID_REQUEST")
        data = dispatch(command, request.get("payload") or {})
        sys.stdout.write(json.dumps({"ok": True, "data": data}))
        return 0
    except BridgeError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc), "code": exc.code}))
        return 1
    except json.JSONDecodeError as exc:
        sys.stdout.write(
            json.dumps({"ok": False, "error": f"invalid JSON: {exc}", "code": "INVALID_JSON"})
        )
        return 1
    except Exception as exc:  # pragma: no cover - defensive catch-all
        sys.stdout.write(
            json.dumps({"ok": False, "error": str(exc), "code": "INTERNAL_ERROR"})
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
