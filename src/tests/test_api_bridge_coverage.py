"""Focused branch and error-contract coverage for :mod:`src.api_bridge`.

These tests complement ``test_api_bridge.py`` by exercising bridge commands
whose success and failure envelopes are part of the TypeScript API contract.
All persistence is redirected to pytest temporary directories.
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import src.api_bridge as bridge
from src.api_bridge import BridgeError, dispatch

ATP_MESSAGE = (
    "#Mode: Build\n"
    "#Context: Exercise the bridge\n"
    "#Priority: Normal\n"
    "#ActionType: Execute\n"
    "#TargetZone: src/tests\n\n"
    "Run the requested task."
)


@pytest.fixture
def bridge_paths(tmp_path: Path) -> dict[str, str]:
    """Return isolated paths and seed one routable registry agent."""
    paths = {
        "db_path": str(tmp_path / "agent_registry.db"),
        "trust_db_path": str(tmp_path / "trust_scores.db"),
        "hebbian_db_path": str(tmp_path / "hebbian_weights.db"),
        "atp_db_path": str(tmp_path / "atp_messages.db"),
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }
    dispatch(
        "registry.register_agent",
        {
            **paths,
            "name": "Bridge Agent",
            "capabilities": [
                "llm_chat",
                "memory_inspection",
                "text_summarization",
                "reasoning",
                "planning",
            ],
            "trust_score": 0.8,
        },
    )
    return paths


def _invoke_main(monkeypatch: pytest.MonkeyPatch, raw: str) -> tuple[int, dict]:
    """Invoke the in-process CLI with isolated text streams."""
    stdout = io.StringIO()
    monkeypatch.setattr(bridge.sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(bridge.sys, "stdout", stdout)
    status = bridge.main([])
    return status, json.loads(stdout.getvalue())


class TestCheckpointReadCommands:
    """Cover checkpoint discovery, integrity lookup, and input failures."""

    def test_checkpoint_list_and_get_report_summary(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Created checkpoints are discoverable and integrity checked."""
        created = dispatch(
            "governance.checkpoints.create",
            {
                **bridge_paths,
                "checkpoint_type": "scheduled",
                "metadata": {"reason": "coverage"},
                "retention_days": 7,
            },
        )

        listing = dispatch("governance.checkpoints.list", bridge_paths)
        assert listing["count"] == 1
        assert listing["checkpoints"][0]["checkpoint_id"] == created["checkpoint_id"]
        assert listing["checkpoints"][0]["agent_count"] == 1
        assert "node_connections" in listing["checkpoints"][0]["hebbian_tables"]

        fetched = dispatch(
            "governance.checkpoints.get",
            {**bridge_paths, "checkpoint_id": created["checkpoint_id"]},
        )
        assert fetched["type"] == "scheduled"
        assert fetched["metadata"] == {"reason": "coverage"}
        assert fetched["integrity_valid"] is True

    def test_checkpoint_get_missing_is_not_found(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Unknown checkpoint identifiers preserve the NOT_FOUND contract."""
        with pytest.raises(BridgeError, match="checkpoint not found") as exc_info:
            dispatch(
                "governance.checkpoints.get",
                {**bridge_paths, "checkpoint_id": "missing"},
            )
        assert exc_info.value.code == "NOT_FOUND"

    def test_rollback_missing_checkpoint_is_invalid_request(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Rollback storage errors are translated into bridge request errors."""
        with pytest.raises(BridgeError, match="Unknown checkpoint") as exc_info:
            dispatch(
                "governance.checkpoints.rollback",
                {
                    **bridge_paths,
                    "checkpoint_id": "missing",
                    "initiated_by": "coverage-operator",
                    "confirmed": True,
                },
            )
        assert exc_info.value.code == "INVALID_REQUEST"

    def test_checkpoint_none_metadata_defaults_to_empty_object(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Explicit null metadata keeps the documented empty-object default."""
        created = dispatch(
            "governance.checkpoints.create",
            {**bridge_paths, "metadata": None},
        )
        assert created["metadata"] == {}

    def test_rollback_legacy_checkpoint_without_hebbian_snapshot(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Legacy registry-only checkpoints remain restorable."""
        store = bridge.CheckpointStore(bridge_paths["checkpoint_dir"])
        created = store.create_checkpoint(
            bridge._store(bridge_paths).export_snapshot(),
            config_snapshot={},
        )
        restored = dispatch(
            "governance.checkpoints.rollback",
            {
                **bridge_paths,
                "checkpoint_id": created["checkpoint_id"],
                "initiated_by": "coverage-operator",
                "confirmed": True,
            },
        )
        assert restored["status"] == "restored"
        assert restored["hebbian"] is None

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"metadata": []}, "metadata must be an object"),
            ({"metadata": ["invalid"]}, "metadata must be an object"),
            ({"retention_days": "later"}, "retention_days must be an integer"),
            ({"retention_days": 0}, "retention_days must be >= 1"),
            ({"checkpoint_type": "unknown"}, "Invalid checkpoint_type"),
        ],
    )
    def test_checkpoint_create_rejects_invalid_options(
        self,
        bridge_paths: dict[str, str],
        changes: dict[str, Any],
        message: str,
    ) -> None:
        """Invalid checkpoint options are translated to INVALID_REQUEST."""
        with pytest.raises(BridgeError, match=message) as exc_info:
            dispatch("governance.checkpoints.create", {**bridge_paths, **changes})
        assert exc_info.value.code == "INVALID_REQUEST"


class TestATPReadAndRoutingCoverage:
    """Cover ATP response storage, capability inference, and route errors."""

    @pytest.mark.parametrize(
        ("message", "payload", "expected"),
        [
            ({}, {"capability": " custom "}, "custom"),
            ({"target_zone": "memory/archive"}, {}, "memory_inspection"),
            ({"action_type": "Summarize"}, {}, "text_summarization"),
            ({"mode": "Synthesize"}, {}, "text_summarization"),
            ({"mode": "Review"}, {}, "reasoning"),
            ({"action_type": "Reflect"}, {}, "reasoning"),
            ({"target_zone": "plans"}, {}, "planning"),
            ({"action_type": "Scaffold"}, {}, "planning"),
            ({}, {}, "llm_chat"),
        ],
    )
    def test_infer_route_capability(
        self, message: dict[str, Any], payload: dict[str, Any], expected: str
    ) -> None:
        """Every bridge inference rule maps to its documented capability."""
        assert bridge._infer_route_capability(message, payload) == expected

    def test_get_response_decodes_persisted_route_and_response(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Response lookup returns queued state and later persisted JSON."""
        sent = dispatch("atp.send", {**bridge_paths, "message": ATP_MESSAGE})
        queued = dispatch(
            "atp.get_response",
            {**bridge_paths, "message_id": sent["message_id"]},
        )
        assert queued == {
            "message_id": sent["message_id"],
            "status": "queued",
            "response": None,
            "route": None,
        }

        with sqlite3.connect(bridge_paths["atp_db_path"]) as conn:
            conn.execute(
                "UPDATE atp_messages SET status = ?, route_json = ?, response_json = ? "
                "WHERE message_id = ?",
                (
                    "completed",
                    json.dumps({"agent_name": "Bridge Agent"}),
                    json.dumps({"summary": "done"}),
                    sent["message_id"],
                ),
            )

        completed = dispatch(
            "atp.get_response",
            {**bridge_paths, "message_id": sent["message_id"]},
        )
        assert completed["status"] == "completed"
        assert completed["route"] == {"agent_name": "Bridge Agent"}
        assert completed["response"] == {"summary": "done"}

    def test_get_response_missing_message_is_not_found(self, tmp_path: Path) -> None:
        """Response lookup preserves NOT_FOUND for an unknown ATP message."""
        with pytest.raises(BridgeError, match="ATP message not found") as exc_info:
            dispatch(
                "atp.get_response",
                {
                    "atp_db_path": str(tmp_path / "atp.db"),
                    "message_id": "missing",
                },
            )
        assert exc_info.value.code == "NOT_FOUND"

    def test_format_accepts_nested_message_object(self) -> None:
        """ATP formatting accepts the controller's nested message shape."""
        result = dispatch(
            "atp.format",
            {
                "message": {
                    "mode": "Review",
                    "context": "Inspect bridge coverage",
                    "priority": "High",
                    "actionType": "Reflect",
                    "targetZone": "src/api_bridge.py",
                    "specialNotes": "Keep the envelope stable",
                    "content": "Review the bridge.",
                }
            },
        )
        assert result["parsed"]["mode"] == "Review"
        assert result["parsed"]["action_type"] == "Reflect"

    def test_legacy_atp_store_adds_provenance_column(self, tmp_path: Path) -> None:
        """Opening a pre-provenance ATP database performs its migration."""
        db_path = tmp_path / "nested" / "legacy_atp.db"
        db_path.parent.mkdir()
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE atp_messages (
                    message_id TEXT PRIMARY KEY,
                    raw_message TEXT NOT NULL,
                    parsed_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    route_json TEXT,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """)

        result = dispatch("atp.queue", {"atp_db_path": str(db_path)})
        assert result["total"] == 0
        with sqlite3.connect(db_path) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(atp_messages)")
            }
        assert "provenance_id" in columns

    def test_in_memory_atp_store_skips_directory_creation(self) -> None:
        """The special SQLite in-memory path requires no filesystem parent."""
        assert bridge._ensure_atp_store({"atp_db_path": ":memory:"}) == ":memory:"

    @pytest.mark.parametrize(
        ("payload", "code"),
        [
            ({"message_id": 42}, "INVALID_REQUEST"),
            ({"message_id": "missing"}, "NOT_FOUND"),
            ({}, "INVALID_REQUEST"),
        ],
    )
    def test_route_rejects_invalid_message_inputs(
        self,
        tmp_path: Path,
        payload: dict[str, Any],
        code: str,
    ) -> None:
        """Route lookup validates identifiers and requires message content."""
        with pytest.raises(BridgeError) as exc_info:
            dispatch(
                "atp.route",
                {"atp_db_path": str(tmp_path / "atp.db"), **payload},
            )
        assert exc_info.value.code == code

    def test_route_without_any_candidate_is_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Router failures become the stable bridge NOT_FOUND response."""
        monkeypatch.setenv("ARTEMIS_ROUTING_FALLBACK_CAPABILITY", "")
        payload = {
            "db_path": str(tmp_path / "empty_registry.db"),
            "trust_db_path": str(tmp_path / "trust.db"),
            "hebbian_db_path": str(tmp_path / "hebbian.db"),
            "atp_db_path": str(tmp_path / "atp.db"),
            "checkpoint_dir": str(tmp_path / "checkpoints"),
            "message": ATP_MESSAGE,
        }
        with pytest.raises(BridgeError) as exc_info:
            dispatch("atp.route", payload)
        assert exc_info.value.code == "NOT_FOUND"
        assert "No agent found" in str(exc_info.value)

    def test_invalid_routing_float_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed optional routing environment values do not crash routing."""
        monkeypatch.setenv("ARTEMIS_HEBBIAN_ROUTING_ALPHA", "not-a-number")
        assert bridge._env_float("ARTEMIS_HEBBIAN_ROUTING_ALPHA", 0.3) == 0.3

    def test_route_uses_bridge_inference_when_context_has_no_capability(
        self,
        bridge_paths: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The bridge inference fallback remains usable for unresolved contexts."""

        def unresolved(task_context: dict[str, Any], **_: Any) -> dict[str, Any]:
            """Return an unresolved context to exercise the bridge fallback."""
            return task_context

        monkeypatch.setattr(bridge, "resolve_task_context", unresolved)
        message = ATP_MESSAGE.replace("src/tests", "memory/archive")
        result = dispatch("atp.route", {**bridge_paths, "message": message})
        assert result["route"]["required_capability"] == "memory_inspection"
        assert result["route"]["agent_name"] == "Bridge Agent"

    def test_provenance_writes_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Parent and child ATP provenance failures stop bridge processing."""

        class BrokenLogger:
            """Run logger double that always rejects writes."""

            def log_event(self, *args: Any, **kwargs: Any) -> str:
                """Raise the storage failure used by the assertions."""
                raise OSError("disk unavailable")

        monkeypatch.setattr(bridge, "_atp_provenance_logger", lambda _: BrokenLogger())
        with pytest.raises(BridgeError, match="provenance write failed") as parent:
            dispatch("atp.send", {"message": ATP_MESSAGE})
        assert parent.value.code == "BRIDGE_ERROR"

        with pytest.raises(BridgeError, match="provenance write failed") as child:
            bridge._record_atp_child_provenance({}, "parent", "event", {})
        assert child.value.code == "BRIDGE_ERROR"

    def test_default_provenance_logger_is_available(self) -> None:
        """Requests without path overrides use the process-wide run logger."""
        assert bridge._atp_provenance_logger({}) is not None


class TestTrustCoverage:
    """Cover trust metadata, persisted decay, and trust validation."""

    def test_levels_publish_every_threshold(self) -> None:
        """The bridge advertises all canonical trust levels in enum order."""
        result = dispatch("trust.levels")
        assert [item["level"] for item in result["levels"]] == [
            "full",
            "high",
            "medium",
            "low",
            "untrusted",
        ]
        assert result["levels"][0]["threshold"] == 0.9
        assert result["levels"][-1]["threshold"] == 0.0

    def test_apply_decay_updates_store_and_registry(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Aged trust scores decay to their tier floor and remain synchronized."""
        dispatch(
            "trust.set_score",
            {**bridge_paths, "entity_id": "Bridge Agent", "score": 0.8},
        )
        old = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with sqlite3.connect(bridge_paths["trust_db_path"]) as conn:
            conn.execute(
                "UPDATE trust_scores SET last_updated = ? "
                "WHERE entity_type = 'agent' AND entity_id = 'Bridge Agent'",
                (old,),
            )

        result = dispatch("trust.apply_decay", {**bridge_paths, "decay_rate": 0.5})
        decayed = next(
            item for item in result["updated"] if item["entity_id"] == "Bridge Agent"
        )
        assert result["count"] >= 5
        assert decayed["score"] == pytest.approx(0.7)
        registry_record = dispatch(
            "registry.get_agent", {**bridge_paths, "name": "Bridge Agent"}
        )
        assert registry_record["trust_score"] == pytest.approx(0.7)

    @pytest.mark.parametrize(
        ("command", "payload", "message"),
        [
            ("trust.get_score", {"entity_id": "x", "entity_type": 2}, "entity_type"),
            ("trust.set_score", {"entity_id": "x", "entity_type": 2}, "entity_type"),
            ("trust.set_score", {"entity_id": "x"}, "missing required field: score"),
            ("trust.apply_decay", {"decay_rate": 1.1}, "decay_rate must be <= 1.0"),
        ],
    )
    def test_trust_commands_reject_invalid_values(
        self,
        tmp_path: Path,
        command: str,
        payload: dict[str, Any],
        message: str,
    ) -> None:
        """Trust validation failures use INVALID_REQUEST consistently."""
        with pytest.raises(BridgeError, match=message) as exc_info:
            dispatch(
                command,
                {
                    "db_path": str(tmp_path / "registry.db"),
                    "trust_db_path": str(tmp_path / "trust.db"),
                    **payload,
                },
            )
        assert exc_info.value.code == "INVALID_REQUEST"


class TestCLIEnvelopeCoverage:
    """Exercise ``main`` directly so every JSON envelope path is measured."""

    def test_main_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful handler returns zero and a success envelope."""
        status, envelope = _invoke_main(
            monkeypatch,
            json.dumps({"command": "trust.levels", "payload": {}}),
        )
        assert status == 0
        assert envelope["ok"] is True
        assert envelope["data"]["levels"]

    @pytest.mark.parametrize(
        ("raw", "code"),
        [
            ("{not json", "INVALID_JSON"),
            ("", "INVALID_REQUEST"),
            (json.dumps({"payload": {}}), "INVALID_REQUEST"),
            (json.dumps({"command": "missing.command"}), "UNKNOWN_COMMAND"),
        ],
    )
    def test_main_invalid_requests(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, code: str
    ) -> None:
        """Malformed CLI requests return their stable error code."""
        status, envelope = _invoke_main(monkeypatch, raw)
        assert status == 1
        assert envelope["ok"] is False
        assert envelope["code"] == code

    def test_main_handler_bridge_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handler-level BridgeError values retain their explicit code."""

        def fail(_: dict[str, Any]) -> dict[str, Any]:
            """Raise a representative handler bridge error."""
            raise BridgeError("handler rejected request", "INVALID_REQUEST")

        monkeypatch.setitem(bridge.COMMANDS, "test.bridge_error", fail)
        status, envelope = _invoke_main(
            monkeypatch, json.dumps({"command": "test.bridge_error"})
        )
        assert status == 1
        assert envelope == {
            "ok": False,
            "error": "handler rejected request",
            "code": "INVALID_REQUEST",
        }

    def test_main_unexpected_handler_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unexpected handler failures are contained as INTERNAL_ERROR."""

        def fail(_: dict[str, Any]) -> dict[str, Any]:
            """Raise a representative unexpected exception."""
            raise RuntimeError("handler exploded")

        monkeypatch.setitem(bridge.COMMANDS, "test.internal_error", fail)
        status, envelope = _invoke_main(
            monkeypatch, json.dumps({"command": "test.internal_error"})
        )
        assert status == 1
        assert envelope == {
            "ok": False,
            "error": "bridge command failed",
            "code": "INTERNAL_ERROR",
        }


class TestValidationAndAdapterCoverage:
    """Cover public command guards and their error-code adapters."""

    @pytest.mark.parametrize(
        ("command", "changes", "message"),
        [
            ("registry.register_agent", {}, "missing required field: name"),
            (
                "registry.register_agent",
                {"name": "x", "capabilities": [1]},
                "capabilities must be a list of strings",
            ),
            (
                "registry.register_agent",
                {"name": "x", "description": []},
                "description must be a string",
            ),
            (
                "registry.register_agent",
                {"name": "x", "description": ["invalid"]},
                "description must be a string",
            ),
            (
                "registry.register_agent",
                {"name": "x", "role": []},
                "description must be a string",
            ),
            (
                "registry.register_agent",
                {"name": "x", "alignment": "nope"},
                "alignment must be a number",
            ),
            (
                "registry.register_agent",
                {"name": "x", "alignment": -0.1},
                "alignment must be >= 0.0",
            ),
            (
                "registry.register_agent",
                {"name": "x", "alignment": 1.1},
                "alignment must be <= 1.0",
            ),
            (
                "registry.register_agent",
                {"name": "x", "trust_tier": "root"},
                "trust_tier must be",
            ),
            (
                "registry.register_agent",
                {"name": "x", "status": "deleted"},
                "status must be",
            ),
            ("atp.queue", {"limit": "many"}, "limit must be an integer"),
            ("atp.queue", {"limit": 0}, "limit must be >= 1"),
            ("atp.queue", {"limit": 201}, "limit must be <= 200"),
            ("memory.read", {"path": "   "}, "missing required field: path"),
            ("memory.read", {"path": "/tmp/note.md"}, "path must be relative"),
            ("memory.list", {"suffix": []}, "suffix must be a string"),
            ("memory.stats", {"suffix": []}, "suffix must be a string"),
            (
                "memory.write",
                {"path": "x.md", "content": "x", "metadata": []},
                "metadata",
            ),
            ("memory.write", {"path": "x.md", "content": "x", "embed": "yes"}, "embed"),
            ("memory.search", {"query": "x", "tags": "tag"}, "tags must be"),
            (
                "hebbian.sentinel_status",
                {"agent_name": 4},
                "agent_name must be a string",
            ),
            (
                "hebbian.sentinel_status",
                {"task_type": 4},
                "task_type must be a string",
            ),
            (
                "hebbian.sentinel_alerts",
                {"open_only": "yes"},
                "open_only must be a boolean",
            ),
            ("hebbian.update", {}, "missing required field: origin"),
            ("hebbian.update", {"origin": "x"}, "missing required field: target"),
            (
                "hebbian.update",
                {"origin": "x", "target": "y"},
                "missing required field: delta",
            ),
            ("atp.parse", {"message": 3}, "message must be a string"),
            ("atp.send", {}, "missing required field: message"),
        ],
    )
    def test_public_validation_guards(
        self,
        tmp_path: Path,
        command: str,
        changes: dict[str, Any],
        message: str,
    ) -> None:
        """Malformed public command fields fail before storage mutation."""
        vault = tmp_path / "vault"
        vault.mkdir(exist_ok=True)
        payload = {
            "db_path": str(tmp_path / "registry.db"),
            "trust_db_path": str(tmp_path / "trust.db"),
            "hebbian_db_path": str(tmp_path / "hebbian.db"),
            "atp_db_path": str(tmp_path / "atp.db"),
            "checkpoint_dir": str(tmp_path / "checkpoints"),
            "vector_db_path": str(tmp_path / "vector.db"),
            "vault_path": str(vault),
            **changes,
        }
        with pytest.raises(BridgeError, match=message) as exc_info:
            dispatch(command, payload)
        assert exc_info.value.code == "INVALID_REQUEST"

    def test_helpers_cover_non_public_type_guards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Internal helpers reject types already normalized by public handlers."""
        with pytest.raises(BridgeError, match="missing required field: value"):
            bridge._require_str({}, "value", allow_empty=True)
        with pytest.raises(BridgeError, match="path must be a string"):
            bridge._safe_note_path(3)  # type: ignore[arg-type]
        with pytest.raises(BridgeError, match="missing required field: path"):
            bridge._safe_note_path("")
        assert bridge._optional_note_path({"path": None}) == ""
        assert bridge._optional_string_list({"items": None}, "items") is None
        assert bridge._optional_string_list({"items": "a, b,,"}, "items") == [
            "a",
            "b",
        ]

        def fake_data_path(_name: str, configured: str | None = None, **_: Any) -> str:
            """Return a temporary default without touching repository data."""
            return configured or str(tmp_path / "default.db")

        monkeypatch.setattr(bridge, "data_path", fake_data_path)
        resolved = bridge._resolve_db_path(
            {"trust_db_path": str(tmp_path / "trust_scores.db")}
        )
        assert resolved == str(tmp_path / "agent_registry.db")
        fallback = bridge._resolve_db_path(
            {"trust_db_path": ":memory:", "hebbian_db_path": ":memory:"}
        )
        assert fallback == str(tmp_path / "default.db")

        captured: list[str | None] = []

        class FakeCheckpointStore:
            """Capture the checkpoint directory selected by the helper."""

            def __init__(self, checkpoint_dir: str | None = None) -> None:
                captured.append(checkpoint_dir)

        monkeypatch.setattr(bridge, "CheckpointStore", FakeCheckpointStore)
        bridge._checkpoint_store(
            {
                "db_path": ":memory:",
                "trust_db_path": ":memory:",
                "hebbian_db_path": ":memory:",
            }
        )
        assert captured == [None]

    def test_memory_dependencies_validate_search_directories(
        self, tmp_path: Path
    ) -> None:
        """Search directory configuration must be a list of safe paths."""
        vault = tmp_path / "vault"
        vault.mkdir()
        with pytest.raises(BridgeError, match="search_dirs") as exc_info:
            dispatch(
                "memory.write",
                {
                    "vault_path": str(vault),
                    "vector_db_path": str(tmp_path / "vector.db"),
                    "path": "note.md",
                    "content": "text",
                    "search_dirs": "notes",
                },
            )
        assert exc_info.value.code == "INVALID_REQUEST"

    def test_register_aliases_and_update_every_mutable_field(
        self, tmp_path: Path
    ) -> None:
        """Legacy aliases and the complete registry update surface stay wired."""
        db_path = str(tmp_path / "registry.db")
        created = dispatch(
            "registry.register_agent",
            {
                "db_path": db_path,
                "id": "Alias Agent",
                "capabilities": "research, planning",
                "role": "alias role",
                "trustLevel": 0.6,
            },
        )
        assert created["capabilities"] == ["research", "planning"]
        assert created["description"] == "alias role"
        assert created["trust_score"] == pytest.approx(0.6)

        updated = dispatch(
            "registry.update_agent",
            {
                "db_path": db_path,
                "name": "Alias Agent",
                "updates": {
                    "capabilities": ["reasoning"],
                    "role": "updated role",
                    "alignment": 0.7,
                    "accuracy": 0.8,
                    "efficiency": 0.9,
                    "trust_score": 0.75,
                    "trust_tier": "human",
                    "status": "suspended",
                },
            },
        )
        assert updated["capabilities"] == ["reasoning"]
        assert updated["description"] == "updated role"
        assert updated["alignment"] == pytest.approx(0.7)
        assert updated["trust_score"] == pytest.approx(0.75)
        assert updated["trust_tier"] == "human"
        assert updated["status"] == "suspended"

        trust_alias = dispatch(
            "registry.update_agent",
            {
                "db_path": db_path,
                "name": "Alias Agent",
                "updates": {"trustLevel": 0.65},
            },
        )
        assert trust_alias["trust_score"] == pytest.approx(0.65)

    @pytest.mark.parametrize(
        ("command", "payload", "code"),
        [
            (
                "registry.update_agent",
                {"name": "Bridge Agent", "updates": []},
                "INVALID_REQUEST",
            ),
            ("registry.update_agent", {"name": "missing", "updates": {}}, "NOT_FOUND"),
            ("registry.delete_agent", {"name": "missing"}, "NOT_FOUND"),
            (
                "registry.set_agent_status",
                {"name": "Bridge Agent", "status": "invalid"},
                "INVALID_REQUEST",
            ),
            (
                "registry.set_agent_status",
                {"name": "missing", "status": "active"},
                "NOT_FOUND",
            ),
            ("registry.get_violations", {"name": "missing"}, "NOT_FOUND"),
            ("registry.clear_violations", {"name": "missing"}, "NOT_FOUND"),
            (
                "registry.set_trust_tier",
                {"name": "missing", "tier": "human"},
                "NOT_FOUND",
            ),
            (
                "registry.record_violation",
                {"name": "missing", "violation_type": "rate_limit"},
                "NOT_FOUND",
            ),
            (
                "governance.evaluate_update",
                {"agent_name": "missing", "trust_score": 0.5},
                "NOT_FOUND",
            ),
            (
                "governance.evaluate_update",
                {"agent_name": "Bridge Agent", "trust_score": 1.2},
                "INVALID_REQUEST",
            ),
        ],
    )
    def test_registry_and_governance_missing_or_invalid_records(
        self,
        bridge_paths: dict[str, str],
        command: str,
        payload: dict[str, Any],
        code: str,
    ) -> None:
        """Record lookup and governance errors retain their API error codes."""
        with pytest.raises(BridgeError) as exc_info:
            dispatch(command, {**bridge_paths, **payload})
        assert exc_info.value.code == code

    def test_update_validation_and_status_reason(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Update field validators reject bad values and status echoes its reason."""
        invalid_updates = [
            {"description": []},
            {"description": ["invalid"]},
            {"role": []},
            {"trust_tier": "root"},
            {"status": "deleted"},
        ]
        for updates in invalid_updates:
            with pytest.raises(BridgeError) as exc_info:
                dispatch(
                    "registry.update_agent",
                    {**bridge_paths, "name": "Bridge Agent", "updates": updates},
                )
            assert exc_info.value.code == "INVALID_REQUEST"

        status = dispatch(
            "registry.set_agent_status",
            {
                **bridge_paths,
                "name": "Bridge Agent",
                "status": "active",
                "reason": "review complete",
            },
        )
        assert status["reason"] == "review complete"

    def test_invalid_violation_type_is_translated(
        self, bridge_paths: dict[str, str]
    ) -> None:
        """Registry ValueError from a bad violation type becomes INVALID_REQUEST."""
        with pytest.raises(BridgeError, match="Unknown violation_type") as exc_info:
            dispatch(
                "registry.record_violation",
                {
                    **bridge_paths,
                    "name": "Bridge Agent",
                    "violation_type": "made_up",
                },
            )
        assert exc_info.value.code == "INVALID_REQUEST"


class TestMemoryAdapterCoverage:
    """Cover memory path variants, filters, misses, and ValueError translation."""

    def test_file_stats_tag_filter_and_delete_miss(self, tmp_path: Path) -> None:
        """File paths count correctly and tag filtering excludes other notes."""
        vault = tmp_path / "vault"
        vault.mkdir()
        base = {
            "vault_path": str(vault),
            "vector_db_path": str(tmp_path / "vector.db"),
        }
        dispatch(
            "memory.write",
            {**base, "path": "keep.md", "content": "shared topic #keep"},
        )
        dispatch(
            "memory.write",
            {**base, "path": "drop.md", "content": "shared topic #drop"},
        )

        stats = dispatch("memory.stats", {**base, "path": "keep.md"})
        assert stats["note_count"] == 1
        assert stats["total_bytes"] > 0

        missing_stats = dispatch("memory.stats", {**base, "path": "missing"})
        assert missing_stats["note_count"] == 0
        assert missing_stats["total_bytes"] == 0

        filtered = dispatch(
            "memory.search",
            {**base, "query": "shared topic", "tags": ["keep"]},
        )
        assert filtered["count"] >= 1
        assert {item["path"] for item in filtered["results"]} == {"keep.md"}

        with pytest.raises(BridgeError, match="note not found") as exc_info:
            dispatch("memory.delete", {**base, "path": "missing.md"})
        assert exc_info.value.code == "NOT_FOUND"

    @pytest.mark.parametrize(
        ("dependency", "command", "payload"),
        [
            ("manager", "memory.read", {"path": "note.md"}),
            ("dependencies", "memory.write", {"path": "note.md", "content": "x"}),
            ("manager", "memory.list", {}),
            ("dependencies_for_store", "memory.delete", {"path": "note.md"}),
            ("dependencies_for_store", "memory.stats", {}),
            ("dependencies", "memory.search", {"query": "x"}),
        ],
    )
    def test_memory_value_errors_become_invalid_request(
        self,
        monkeypatch: pytest.MonkeyPatch,
        dependency: str,
        command: str,
        payload: dict[str, Any],
    ) -> None:
        """Core memory ValueError values are normalized by each adapter."""

        def fail(*_args: object) -> Any:
            """Raise a representative path validation error."""
            raise ValueError("vault path rejected")

        target = {
            "manager": "_memory_manager",
            "dependencies": "_memory_dependencies",
            "dependencies_for_store": "_memory_dependencies_for_store",
        }[dependency]
        monkeypatch.setattr(bridge, target, fail)
        with pytest.raises(BridgeError, match="vault path rejected") as exc_info:
            dispatch(command, payload)
        assert exc_info.value.code == "INVALID_REQUEST"
