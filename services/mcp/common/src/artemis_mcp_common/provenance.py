"""Shared provenance client for the Artemis City MCP servers.

Mirrors the contract the prove service exposes (``/manifest/bind``, ``/mint``,
``/log``) and that ``services/prove/tool-servers/*/tools/_provenance.py``
already speak, with one deliberate difference: **nothing happens at import**.

The tool-server copies register their session as an import side effect, which
performs network I/O, writes a JSONL mirror, and prints to stderr on failure.
The MCP adapters forbid all three — importing a server must produce no output
and create no files, and artemis-validation's factory runs with
``builtins.open`` and ``socket.create_connection`` patched to raise. So
registration here is an explicit call the CLI entry point makes once it has
decided to serve.

Failure posture follows the fleet: fail-soft by default so a stopped dashboard
does not take the server down, ``PROVENANCE_STRICT=1`` to refuse to serve
without provenance, matching the atp-provenance-logging skill's halt-and-alert
posture.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_DEFAULT_SERVICE_URL = "http://127.0.0.1:8787"
_TIMEOUT_SECONDS = 2

# Credential shapes stripped before anything leaves this process. The service
# redacts secret-named keys; this covers values that arrive inside free text.
_REDACTED = "[REDACTED]"
_SECRET_MARKERS = ("bearer ", "sk-", "ghp_", "github_pat_", "xox", "akia")


class ProvenanceUnavailable(RuntimeError):
    """Raised only under ``PROVENANCE_STRICT=1`` when registration fails."""


def _redact(value: object) -> str:
    text = str(value)
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return _REDACTED
    return text[:200]


@dataclass(slots=True)
class ProvenanceSession:
    """A registered provenance root plus the manifest binding its children need.

    Construct, then call :meth:`register` exactly once. Re-binding a manifest
    layer nulls everything beneath it and makes later children 422, so
    registration refuses to run twice.
    """

    server_name: str
    workspace: str
    service_url: str = field(
        default_factory=lambda: os.getenv(
            "PROVENANCE_SERVICE_URL", _DEFAULT_SERVICE_URL
        ).rstrip("/")
    )
    strict: bool = field(
        default_factory=lambda: os.getenv("PROVENANCE_STRICT", "0") == "1"
    )
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    root_prov_id: str | None = None
    binding_id: str | None = None
    available: bool = False

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        request = urllib.request.Request(
            f"{self.service_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ):
            return None

    def _bind(self, layer: str, body: dict[str, Any], parent_ref: str | None) -> str | None:
        payload: dict[str, Any] = {
            "layer": layer,
            "manifest_binding_id": self.binding_id,
            "body": body,
            "parent_ref": parent_ref,
        }
        if layer == "declaration":
            payload["session_id"] = self.session_id
        response = self._post("/manifest/bind", payload)
        return response.get("layer_hash") if response else None

    def register(self) -> bool:
        """Bind the four manifest layers and mint this process's ATP root.

        Only fields this process can honestly measure are filled in. A tool
        server has no real route emitter, so ``route`` is bound as an explicit
        ``not_polled`` placeholder rather than a fabricated value.
        """
        if self.root_prov_id is not None:
            return self.available
        self.binding_id = f"{self.server_name}-{self.session_id}"

        layers: tuple[tuple[str, dict[str, Any]], ...] = (
            ("declaration", {"identity": {"agent_id": self.server_name}}),
            ("version", {"component_id": self.server_name, "build_inputs": {}}),
            (
                "session",
                {
                    "session_id": self.session_id,
                    "scope": {"workspace": self.workspace},
                    "execution_location": {"placement": "local"},
                },
            ),
            (
                "route",
                {
                    "model": {"id": "n/a"},
                    "health": {"capacity_state": "not_polled", "last_verified": None},
                },
            ),
        )

        parent_ref: str | None = None
        for name, body in layers:
            parent_ref = self._bind(name, body, parent_ref)
            if parent_ref is None:
                return self._fail("manifest binding refused or unreachable")

        minted = self._post(
            "/mint",
            {
                "agent_id": self.server_name,
                "actor": self.server_name,
                "model": None,
                "atp_context": f"{self.server_name} stdio server session",
                "tags": ["tool-server", "session-registration"],
            },
        )
        if not minted or not minted.get("prov_id"):
            return self._fail("mint refused or unreachable")

        self.root_prov_id = minted["prov_id"]
        self.available = True
        return True

    def _fail(self, reason: str) -> bool:
        self.available = False
        if self.strict:
            raise ProvenanceUnavailable(
                f"{self.server_name}: PROVENANCE_STRICT=1 and the provenance service at "
                f"{self.service_url} is unavailable ({reason}); refusing to serve "
                "tools without provenance."
            )
        return False

    def log(
        self,
        *,
        phase: str,
        action_type: str,
        target: str,
        status: str = "ok",
        payload_summary: str = "",
        inputs: dict[str, Any] | None = None,
        error: str | None = None,
        latency_ms: int | None = None,
        tags: tuple[str, ...] = (),
    ) -> str | None:
        """Log one child line item. Returns its ``prov_id``, or ``None``.

        Never raises: a provenance outage mid-run must not take down a server
        that has already been admitted. Strictness is enforced at registration.
        """
        if not self.available or self.root_prov_id is None:
            return None
        prov_id = str(uuid.uuid4())
        sent = self._post(
            "/log",
            {
                "prov_id": prov_id,
                "parent_prov_id": self.root_prov_id,
                "manifest_binding_id": self.binding_id,
                "agent_id": self.server_name,
                "actor": self.server_name,
                "phase": phase,
                "action_type": action_type,
                "target": target,
                "status": status,
                "payload_summary": payload_summary[:280],
                "input": {k: _redact(v) for k, v in (inputs or {}).items()},
                "error": error,
                "latency_ms": latency_ms,
                "ts": datetime.now(UTC).isoformat(),
                "tags": list(tags),
            },
        )
        return prov_id if sent is not None else None
