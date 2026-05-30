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
    limit = int(payload.get("limit", 100))
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


COMMANDS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "registry.list_agents": _list_agents,
    "registry.get_agent": _get_agent,
    "registry.get_violations": _get_violations,
    "registry.clear_violations": _clear_violations,
    "registry.set_trust_tier": _set_trust_tier,
    "registry.record_violation": _record_violation,
}


def dispatch(command: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Run a bridge command and return its JSON-able result dict.

    Raises :class:`BridgeError` for unknown commands or handler failures.
    """
    handler = COMMANDS.get(command)
    if handler is None:
        raise BridgeError(f"unknown command: {command}", code="UNKNOWN_COMMAND")
    return handler(payload or {})


def main(argv=None) -> int:
    """CLI entry point: read one JSON request from stdin, write one to stdout."""
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
