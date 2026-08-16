"""Tests for the TS<->Python JSON bridge (src/api_bridge.py)."""

import json
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import src.api_bridge as api_bridge_module
from src.agents.base_agent import BaseAgent
from src.api_bridge import BridgeError, dispatch
from src.integration.agent_registry import QUARANTINE_THRESHOLD, AgentRegistry
from src.integration.memory_store_factory import MemoryStoreConfigurationError
from src.integration.sql_memory_store import (
    IdempotencyConflictError,
    MemoryStoreError,
)
from src.mcp.hebbian_weights import HebbianWeightManager


class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success"}


@pytest.fixture
def db(tmp_path):
    """A registry DB seeded with one agent; returns its path.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    path = str(tmp_path / "registry.db")
    reg = AgentRegistry(db_path=path)
    reg.register_agent(_StubAgent("Alpha", capabilities=["research", "code"]))
    return path


@pytest.fixture
def repo_root():
    import pathlib

    return pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def vault(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
    return path


# ---------------------------------------------------------------------------
# dispatch() — direct, in-process
# ---------------------------------------------------------------------------
class TestDispatch:
    """Provide the TestDispatch abstraction used by this module."""

    def test_list_agents(self, db):
        """Test that list agents.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch("registry.list_agents", {"db_path": db})
        assert result["total"] == 1
        agent = result["agents"][0]
        assert agent["name"] == "Alpha"
        assert agent["capabilities"] == ["research", "code"]
        assert agent["trust_tier"] == "monitored"
        assert agent["status"] == "active"

    def test_get_agent(self, db):
        """Test that get agent.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert result["name"] == "Alpha"
        assert result["composite_score"] is not None

    def test_get_agent_missing(self, db):
        """Test that get agent missing.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.get_agent", {"db_path": db, "name": "ghost"})
        assert exc.value.code == "NOT_FOUND"

    def test_unknown_command(self, db):
        """Test that unknown command.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.bogus", {"db_path": db})
        assert exc.value.code == "UNKNOWN_COMMAND"

    def test_missing_required_field(self, db):
        """Test that missing required field.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.get_agent", {"db_path": db})
        assert exc.value.code == "INVALID_REQUEST"

    def test_record_and_get_violations(self, db):
        """Test that record and get violations.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "registry.record_violation",
            {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
        )
        result = dispatch("registry.get_violations", {"db_path": db, "name": "Alpha"})
        assert result["violation_count"] == 1
        assert result["quarantined"] is False
        assert len(result["violations"]) == 1

    def test_get_violations_non_integer_limit(self, db):
        """A non-integer 'limit' must surface as INVALID_REQUEST, not 500.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.get_violations",
                {"db_path": db, "name": "Alpha", "limit": "abc"},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_get_violations_zero_limit(self, db):
        """Test that get violations zero limit.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.get_violations",
                {"db_path": db, "name": "Alpha", "limit": 0},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_record_violation_quarantines(self, db):
        """Test that record violation quarantines.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for _ in range(QUARANTINE_THRESHOLD):
            dispatch(
                "registry.record_violation",
                {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
            )
        result = dispatch("registry.get_violations", {"db_path": db, "name": "Alpha"})
        assert result["quarantined"] is True

    def test_clear_violations(self, db):
        """Test that clear violations.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for _ in range(QUARANTINE_THRESHOLD):
            dispatch(
                "registry.record_violation",
                {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
            )
        result = dispatch(
            "registry.clear_violations",
            {"db_path": db, "name": "Alpha", "rationale": "reviewed"},
        )
        assert result["cleared"] == QUARANTINE_THRESHOLD
        assert result["quarantined"] is False
        assert result["violation_count"] == 0

    def test_clear_with_invalid_tier(self, db):
        """Test that clear with invalid tier.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.clear_violations",
                {"db_path": db, "name": "Alpha", "override_tier": "god"},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_set_trust_tier(self, db):
        """Test that set trust tier.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "registry.set_trust_tier", {"db_path": db, "name": "Alpha", "tier": "human"}
        )
        assert result["trust_tier"] == "human"

    def test_set_trust_tier_invalid(self, db):
        """Test that set trust tier invalid.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.set_trust_tier",
                {"db_path": db, "name": "Alpha", "tier": "nope"},
            )
        assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# ATP and memory bridge commands
# ---------------------------------------------------------------------------
class TestATPCommands:
    def test_parse_atp_message_uses_canonical_values(self):
        message = """
        #Mode: Build
        #Context: Create bridge tests
        #Priority: Normal
        #Action: Execute
        #TargetZone: src/tests
        """

        result = dispatch("atp.parse", {"message": message})

        parsed = result["message"]
        assert parsed["mode"] == "Build"
        assert parsed["priority"] == "Normal"
        assert parsed["action_type"] == "Execute"
        assert result["metrics"]["has_headers"] is True

    def test_validate_malformed_atp_returns_validation_errors(self):
        result = dispatch(
            "atp.validate",
            {"message": "plain text without ATP headers", "strict": True},
        )

        validation = result["validation"]
        assert validation["is_valid"] is False
        assert any("ATP headers" in error for error in validation["errors"])

    def test_parse_atp_missing_message(self):
        with pytest.raises(BridgeError) as exc:
            dispatch("atp.parse", {})
        assert exc.value.code == "INVALID_REQUEST"


class TestMemoryCommands:
    def test_write_read_list_and_search(self, vault, tmp_path):
        payload = {
            "vault_path": str(vault),
            "vector_db_path": str(tmp_path / "vector.db"),
            "path": "notes/mars.md",
            "content": "mars mission overview",
            "metadata": {"source": "test"},
        }

        write_result = dispatch("memory.write", payload)
        assert write_result["status"] == "success"
        assert write_result["path"] == "notes/mars.md"
        assert (vault / "notes" / "mars.md").read_text() == "mars mission overview"

        read_result = dispatch(
            "memory.read",
            {"vault_path": str(vault), "path": "notes/mars.md"},
        )
        assert read_result["status"] == "success"
        assert read_result["content"] == "mars mission overview"

        list_result = dispatch(
            "memory.list",
            {"vault_path": str(vault), "path": "notes"},
        )
        assert list_result == {
            "path": "notes",
            "files": ["mars.md"],
            "count": 1,
            "source": "obsidian",
        }

        search_result = dispatch(
            "memory.search",
            {
                "vault_path": str(vault),
                "vector_db_path": str(tmp_path / "vector.db"),
                "query": "mars",
                "limit": 5,
            },
        )
        assert search_result["count"] >= 1
        assert search_result["results"][0]["path"] == "notes/mars.md"

    def test_memory_read_missing_note(self, vault):
        with pytest.raises(BridgeError) as exc:
            dispatch("memory.read", {"vault_path": str(vault), "path": "missing.md"})
        assert exc.value.code == "NOT_FOUND"

    def test_memory_write_missing_fields(self, vault):
        with pytest.raises(BridgeError) as exc:
            dispatch("memory.write", {"vault_path": str(vault), "content": "x"})
        assert exc.value.code == "INVALID_REQUEST"

    def test_memory_write_rejects_traversal(self, vault):
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "memory.write",
                {
                    "vault_path": str(vault),
                    "path": "../escape.md",
                    "content": "blocked",
                },
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_memory_stats_and_delete(self, vault, tmp_path):
        base_payload = {
            "vault_path": str(vault),
            "vector_db_path": str(tmp_path / "vector.db"),
        }
        dispatch(
            "memory.write",
            {
                **base_payload,
                "path": "notes/delete-me.md",
                "content": "delete me #cleanup",
            },
        )

        stats = dispatch("memory.stats", base_payload)
        assert stats["note_count"] == 1
        assert stats["vector_count"] == 1

        deleted = dispatch(
            "memory.delete", {**base_payload, "path": "notes/delete-me.md"}
        )
        assert deleted["deleted"] is True
        assert not (vault / "notes" / "delete-me.md").exists()


def test_memory_dependencies_injects_the_shared_sql_store(monkeypatch):
    """Bridge requests use the same runtime SQL-store factory as the MCP path."""
    sql_store = object()
    factory = Mock(return_value=sql_store)
    captured: dict[str, object] = {}

    class FakeMemoryBus:
        def __init__(self, manager, vector_store, **kwargs):
            captured["manager"] = manager
            captured["vector_store"] = vector_store
            captured.update(kwargs)

    manager_factory = Mock(return_value=object())
    vector_factory = Mock(return_value=object())
    monkeypatch.setattr(api_bridge_module, "create_sql_memory_store", factory)
    monkeypatch.setattr(api_bridge_module, "_memory_manager", manager_factory)
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", vector_factory)
    monkeypatch.setattr(api_bridge_module, "MemoryBus", FakeMemoryBus)

    returned_manager, bus = api_bridge_module._memory_dependencies({})

    factory.assert_called_once_with()
    assert captured["sql_store"] is sql_store
    assert returned_manager is captured["manager"]
    manager_factory.assert_not_called()
    vector_factory.assert_not_called()
    assert bus is not None


def test_explicit_vector_database_path_stays_legacy_without_sql_store(monkeypatch):
    """Test-only vector database selection cannot enable a live SQL store."""
    factory = Mock(return_value=None)
    captured: dict[str, object] = {}

    class FakeMemoryBus:
        def __init__(self, manager, vector_store, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "legacy")
    monkeypatch.setattr(api_bridge_module, "create_sql_memory_store", factory)
    monkeypatch.setattr(api_bridge_module, "_memory_manager", lambda _: object())
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", lambda **_: object())
    monkeypatch.setattr(api_bridge_module, "MemoryBus", FakeMemoryBus)

    api_bridge_module._memory_dependencies({"vector_db_path": "/tmp/test-vector.db"})

    factory.assert_called_once_with()
    assert captured["sql_store"] is None


def test_explicit_vector_database_path_does_not_bypass_sql_configuration(monkeypatch):
    """An explicit SQL backend remains fail-closed with a vector-path override."""
    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "postgres")
    monkeypatch.delenv("ARTEMIS_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.setattr(api_bridge_module, "_memory_manager", lambda _: object())
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", lambda **_: object())

    with pytest.raises(BridgeError) as error:
        api_bridge_module._memory_dependencies(
            {"vector_db_path": "/tmp/test-vector.db"}
        )

    assert error.value.code == "MEMORY_DATABASE_CONFIGURATION_ERROR"


def test_sql_configuration_fails_before_local_memory_dependencies(monkeypatch):
    """Broken SQL configuration cannot construct a vault or local vector store."""
    manager = Mock()
    vector_store = Mock()
    monkeypatch.setattr(
        api_bridge_module,
        "create_sql_memory_store",
        Mock(side_effect=MemoryStoreConfigurationError("postgres://fake-dsn")),
    )
    monkeypatch.setattr(api_bridge_module, "_memory_manager", manager)
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", vector_store)

    with pytest.raises(BridgeError) as error:
        api_bridge_module._memory_dependencies({"vector_db_path": "/tmp/vector.db"})

    assert error.value.code == "MEMORY_DATABASE_CONFIGURATION_ERROR"
    assert str(error.value) == "memory database configuration is invalid"
    assert error.value.__cause__ is None
    manager.assert_not_called()
    vector_store.assert_not_called()


def test_sql_exact_read_does_not_construct_unhealthy_projections(monkeypatch):
    """Canonical reads reach SQL without constructing vector or vault adapters."""
    calls: list[str] = []
    revision = SimpleNamespace(
        content="canonical SQL bytes",
        metadata={"kind": "canonical"},
        record_id="record-1",
        revision=4,
    )

    class RecordingSqlStore:
        def get_current(self, relative_path):
            calls.append(f"sql.get_current:{relative_path}")
            return revision

    vector_constructor = Mock(side_effect=OSError("vector://secret-host"))
    vault_constructor = Mock(side_effect=OSError("vault secret path"))
    monkeypatch.setattr(
        api_bridge_module,
        "create_sql_memory_store",
        Mock(return_value=RecordingSqlStore()),
    )
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", vector_constructor)
    monkeypatch.setattr(api_bridge_module, "ObsidianManager", vault_constructor)

    result = dispatch("memory.read", {"path": "Notes/canonical.md"})

    assert result["content"] == "canonical SQL bytes"
    assert result["revision"] == 4
    assert calls == ["sql.get_current:Notes/canonical.md"]
    vector_constructor.assert_not_called()
    vault_constructor.assert_not_called()


class _RecordingBridgeSqlStore:
    """Minimal SQL seam that records canonical work before projections."""

    def __init__(self, calls):
        self.calls = calls
        self.current = None
        self.status = "pending"

    def stage_write(self, **kwargs):
        self.calls.append("sql.stage")
        self.current = SimpleNamespace(
            relative_path=kwargs["relative_path"],
            content=kwargs["content"],
            metadata=dict(kwargs["metadata"] or {}),
            record_id="record-1",
            memory_id="memory-1",
            revision=1,
            idempotency_key=kwargs["idempotency_key"],
            content_sha256="canonical-hash",
        )
        return SimpleNamespace(
            revision=self.current,
            event_id="event-1",
            projection_status=self.status,
            duplicate=False,
        )

    @contextmanager
    def projection_guard(self, _relative_path):
        self.calls.append("sql.guard")
        yield self.current

    def mark_delivered(self, _event_id):
        self.calls.append("sql.mark_delivered")
        self.status = "delivered"

    def mark_projection_failed(self, _event_id, error_code):
        self.calls.append(f"sql.pending:{error_code}")
        self.status = "pending"

    def get_current(self, relative_path):
        self.calls.append(f"sql.get_current:{relative_path}")
        return self.current


def test_sql_write_commits_before_failing_vector_construction(monkeypatch):
    """An unhealthy vector adapter becomes pending only after canonical commit."""
    calls: list[str] = []
    sql_store = _RecordingBridgeSqlStore(calls)

    def fail_vector(**_kwargs):
        calls.append("vector.construct")
        raise OSError("vector driver postgres://secret-host/db")

    vault_constructor = Mock(side_effect=OSError("vault secret path"))
    monkeypatch.setattr(
        api_bridge_module,
        "create_sql_memory_store",
        Mock(return_value=sql_store),
    )
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", fail_vector)
    monkeypatch.setattr(api_bridge_module, "ObsidianManager", vault_constructor)

    result = dispatch(
        "memory.write", {"path": "Notes/vector.md", "content": "canonical"}
    )

    assert calls[:3] == ["sql.stage", "sql.guard", "vector.construct"]
    assert calls[-1] == "sql.pending:vector_projection_failed"
    assert result["status"] == "accepted"
    assert result["sql_status"] == "committed"
    assert result["vector_status"] == "pending"
    assert result["obsidian_status"] == "pending"
    assert "postgres://" not in json.dumps(result)
    vault_constructor.assert_not_called()


def test_sql_write_commits_before_failing_vault_construction(monkeypatch):
    """An unhealthy vault adapter leaves SQL readable and projection pending."""
    calls: list[str] = []
    sql_store = _RecordingBridgeSqlStore(calls)

    class RecordingVector:
        def __init__(self, **_kwargs):
            calls.append("vector.construct")

        def upsert(self, _doc_id, _content, _metadata):
            calls.append("vector.upsert")

    def fail_vault(**_kwargs):
        calls.append("vault.construct")
        raise OSError("vault at /secret/operator/path is unavailable")

    monkeypatch.setattr(
        api_bridge_module,
        "create_sql_memory_store",
        Mock(return_value=sql_store),
    )
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", RecordingVector)
    monkeypatch.setattr(api_bridge_module, "ObsidianManager", fail_vault)

    result = dispatch(
        "memory.write", {"path": "Notes/vault.md", "content": "canonical"}
    )
    read_result = dispatch("memory.read", {"path": "Notes/vault.md"})

    assert calls[:5] == [
        "sql.stage",
        "sql.guard",
        "vector.construct",
        "vector.upsert",
        "vault.construct",
    ]
    assert result["status"] == "accepted"
    assert result["vector_status"] == "delivered"
    assert result["obsidian_status"] == "pending"
    assert read_result["content"] == "canonical"
    assert calls.count("vault.construct") == 1
    assert "/secret/operator/path" not in json.dumps(result)


def test_memory_write_forwards_explicit_idempotency_key(monkeypatch):
    """The public bridge preserves the caller's opaque retry identity."""
    bus = Mock()
    bus.write_note_with_embedding.return_value = {"status": "success"}
    monkeypatch.setattr(
        api_bridge_module, "_memory_dependencies", lambda _payload: (Mock(), bus)
    )

    dispatch(
        "memory.write",
        {
            "path": "Notes/retry.md",
            "content": "canonical",
            "idempotency_key": "caller-operation-42",
        },
    )

    bus.write_note_with_embedding.assert_called_once_with(
        "Notes/retry.md",
        "canonical",
        metadata=None,
        embed=True,
        idempotency_key="caller-operation-42",
        provenance_id=None,
        source_agent=None,
    )


def test_memory_write_forwards_validated_provenance_identity(monkeypatch):
    """Origin identity reaches the SQL record fields rather than metadata alone."""
    bus = Mock()
    bus.write_note_with_embedding.return_value = {"status": "success"}
    monkeypatch.setattr(
        api_bridge_module, "_memory_dependencies", lambda _payload: (Mock(), bus)
    )
    provenance_id = "6d60a6ab-00aa-4a45-8b35-07723918bacc"

    dispatch(
        "memory.write",
        {
            "path": "Notes/provenance.md",
            "content": "canonical",
            "provenance_id": provenance_id,
            "source_agent": "Artemis Orchestrator",
        },
    )

    assert (
        bus.write_note_with_embedding.call_args.kwargs["provenance_id"]
        == provenance_id
    )
    assert (
        bus.write_note_with_embedding.call_args.kwargs["source_agent"]
        == "Artemis Orchestrator"
    )


@pytest.mark.parametrize("invalid_provenance", ["", "not-a-uuid", 42])
def test_memory_write_rejects_invalid_provenance_before_dependencies(
    monkeypatch, invalid_provenance
):
    dependencies = Mock()
    monkeypatch.setattr(api_bridge_module, "_memory_dependencies", dependencies)

    with pytest.raises(BridgeError) as error:
        dispatch(
            "memory.write",
            {
                "path": "Notes/provenance.md",
                "content": "canonical",
                "provenance_id": invalid_provenance,
            },
        )

    assert error.value.code == "INVALID_REQUEST"
    dependencies.assert_not_called()


@pytest.mark.parametrize("invalid_key", ["", "   ", 42, [], {}])
def test_memory_write_rejects_invalid_idempotency_key(monkeypatch, invalid_key):
    """Blank and non-string retry identities fail before dependency creation."""
    dependencies = Mock()
    monkeypatch.setattr(api_bridge_module, "_memory_dependencies", dependencies)

    with pytest.raises(BridgeError) as error:
        dispatch(
            "memory.write",
            {
                "path": "Notes/retry.md",
                "content": "canonical",
                "idempotency_key": invalid_key,
            },
        )

    assert error.value.code == "INVALID_REQUEST"
    dependencies.assert_not_called()


def test_memory_read_returns_canonical_sql_bytes_not_stale_vault(monkeypatch):
    """The public exact read cannot bypass the bus's SQL authority."""
    manager = Mock()
    manager.read_note.return_value = "stale vault bytes"
    bus = Mock()
    bus.read_exact.return_value = {
        "source": "exact",
        "path": "Notes/pending.md",
        "content": "canonical pending bytes",
        "score": 1.0,
        "record_id": "record-1",
        "revision": 2,
    }
    monkeypatch.setattr(
        api_bridge_module, "_memory_dependencies", lambda _payload: (manager, bus)
    )
    monkeypatch.setattr(api_bridge_module, "_memory_manager", lambda _payload: manager)

    result = dispatch("memory.read", {"path": "Notes/pending.md"})

    assert result["content"] == "canonical pending bytes"
    assert result["record_id"] == "record-1"
    manager.read_note.assert_not_called()


def test_memory_read_missing_sql_revision_does_not_return_stale_vault(monkeypatch):
    """A missing SQL head stays missing even when old projection bytes exist."""
    manager = Mock()
    manager.read_note.return_value = "orphaned vault bytes"
    bus = Mock()
    bus.read_exact.return_value = None
    monkeypatch.setattr(
        api_bridge_module, "_memory_dependencies", lambda _payload: (manager, bus)
    )
    monkeypatch.setattr(api_bridge_module, "_memory_manager", lambda _payload: manager)

    with pytest.raises(BridgeError) as error:
        dispatch("memory.read", {"path": "Notes/missing.md"})

    assert error.value.code == "NOT_FOUND"
    manager.read_note.assert_not_called()


def test_sql_memory_list_uses_canonical_root_and_direct_folder_heads(monkeypatch):
    """Public listing includes SQL-only records without enumerating Obsidian."""
    sql_store = object()
    bus = Mock(sql_store=sql_store)
    bus.list_current.side_effect = [
        [
            {"relative_path": "root.md", "content": "root"},
            {"relative_path": "notes/a.md", "content": "a"},
        ],
        [
            {"relative_path": "notes/a.md", "content": "a"},
            {"relative_path": "notes/nested/b.md", "content": "b"},
        ],
    ]
    manager = Mock()
    monkeypatch.setattr(
        api_bridge_module, "create_sql_memory_store", Mock(return_value=sql_store)
    )
    monkeypatch.setattr(
        api_bridge_module,
        "_memory_dependencies_for_store",
        lambda _payload, _store: (manager, bus),
    )

    root = dispatch("memory.list", {})
    nested = dispatch("memory.list", {"path": "notes"})

    assert root == {
        "path": "",
        "files": ["root.md"],
        "count": 1,
        "source": "sql",
    }
    assert nested == {
        "path": "notes",
        "files": ["a.md"],
        "count": 1,
        "source": "sql",
    }
    assert bus.list_current.call_args_list == [call(""), call("notes")]
    manager.list_notes_in_folder.assert_not_called()


def test_sql_memory_stats_supports_exact_file_and_suffix(monkeypatch):
    """SQL stats preserve exact-file behavior and report projection count unknown."""
    sql_store = object()
    bus = Mock(sql_store=sql_store)
    bus.read_exact.return_value = {
        "path": "notes/a.md",
        "content": "canonical bytes",
    }
    manager = Mock()
    monkeypatch.setattr(
        api_bridge_module, "create_sql_memory_store", Mock(return_value=sql_store)
    )
    monkeypatch.setattr(
        api_bridge_module,
        "_memory_dependencies_for_store",
        lambda _payload, _store: (manager, bus),
    )

    result = dispatch("memory.stats", {"path": "notes/a.md", "suffix": ".md"})

    assert result == {
        "status": "success",
        "path": "notes/a.md",
        "note_count": 1,
        "total_bytes": len("canonical bytes".encode("utf-8")),
        "vector_count": None,
        "source": "sql",
        "projection_stats": "not_checked",
    }
    bus.list_current.assert_not_called()
    manager._get_folder_path.assert_not_called()


def test_sql_memory_stats_treats_unsuffixed_path_as_folder(monkeypatch):
    """SQL folder stats list canonical heads instead of exact-reading a folder."""
    sql_store = object()
    bus = Mock(sql_store=sql_store)
    bus.read_exact.side_effect = ValueError("memory path must name a file")
    bus.list_current.return_value = [
        {"relative_path": "notes/a.md", "content": "alpha"},
        {"relative_path": "notes/b.txt", "content": "beta"},
    ]
    manager = Mock()
    monkeypatch.setattr(
        api_bridge_module, "create_sql_memory_store", Mock(return_value=sql_store)
    )
    monkeypatch.setattr(
        api_bridge_module,
        "_memory_dependencies_for_store",
        lambda _payload, _store: (manager, bus),
    )

    result = dispatch("memory.stats", {"path": "notes", "suffix": ".md"})

    assert result["note_count"] == 1
    assert result["total_bytes"] == len("alpha".encode("utf-8"))
    assert result["source"] == "sql"
    bus.read_exact.assert_not_called()
    bus.list_current.assert_called_once_with("notes")


def test_sql_memory_delete_is_rejected_before_projection_side_effects(monkeypatch):
    """SQL mode rejects deletes until canonical tombstones exist."""
    sql_store = object()
    manager = Mock()
    vector_store = Mock()
    monkeypatch.setattr(
        api_bridge_module, "create_sql_memory_store", Mock(return_value=sql_store)
    )
    monkeypatch.setattr(api_bridge_module, "_memory_manager", manager)
    monkeypatch.setattr(api_bridge_module, "LocalVectorStore", vector_store)

    with pytest.raises(BridgeError) as error:
        dispatch("memory.delete", {"path": "Notes/canonical.md"})

    assert error.value.code == "MEMORY_DELETE_UNSUPPORTED"
    manager.assert_not_called()
    vector_store.assert_not_called()


@pytest.mark.parametrize(
    ("storage_error", "expected_code"),
    [
        (
            MemoryStoreError("driver failed for postgres://fake-secret-host/db"),
            "MEMORY_STORAGE_UNAVAILABLE",
        ),
        (
            IdempotencyConflictError("conflict at postgres://fake-secret-host/db"),
            "MEMORY_IDEMPOTENCY_CONFLICT",
        ),
    ],
)
def test_memory_write_sanitizes_storage_failures(
    monkeypatch, caplog, storage_error, expected_code
):
    """Bridge responses and logs expose only stable storage failure reasons."""
    bus = Mock()
    bus.write_note_with_embedding.side_effect = storage_error
    monkeypatch.setattr(
        api_bridge_module, "_memory_dependencies", lambda _payload: (Mock(), bus)
    )

    with caplog.at_level("ERROR"), pytest.raises(BridgeError) as error:
        dispatch("memory.write", {"path": "Notes/write.md", "content": "body"})

    assert error.value.code == expected_code
    assert str(error.value) in {
        "canonical memory storage is unavailable",
        "memory idempotency key conflicts with an existing write",
    }
    assert error.value.__cause__ is None
    assert "postgres://" not in str(error.value)
    assert "postgres://" not in caplog.text


class TestAgentMutationCommands:
    def test_register_update_suspend_activate_and_delete_agent(self, tmp_path):
        db_path = str(tmp_path / "registry.db")

        created = dispatch(
            "registry.register_agent",
            {
                "db_path": db_path,
                "name": "Bridge Agent",
                "capabilities": ["llm_chat", "planning"],
                "description": "Created by bridge",
                "trust_score": 0.7,
            },
        )
        assert created["name"] == "Bridge Agent"
        assert created["capabilities"] == ["llm_chat", "planning"]

        updated = dispatch(
            "registry.update_agent",
            {
                "db_path": db_path,
                "name": "Bridge Agent",
                "updates": {"capabilities": ["reasoning"], "status": "active"},
            },
        )
        assert updated["capabilities"] == ["reasoning"]

        suspended = dispatch(
            "registry.set_agent_status",
            {"db_path": db_path, "name": "Bridge Agent", "status": "suspended"},
        )
        assert suspended["status"] == "suspended"

        activated = dispatch(
            "registry.set_agent_status",
            {"db_path": db_path, "name": "Bridge Agent", "status": "active"},
        )
        assert activated["status"] == "active"

        deleted = dispatch(
            "registry.delete_agent", {"db_path": db_path, "name": "Bridge Agent"}
        )
        assert deleted == {"name": "Bridge Agent", "deleted": True}


class TestATPBackedCommands:
    def test_atp_queue_history_route_and_metadata(self, tmp_path, db):
        atp_db = str(tmp_path / "atp.db")
        registry = AgentRegistry(db_path=db)
        registry.register_agent(_StubAgent("Builder", capabilities=["llm_chat"]))
        message = (
            "#Mode: Build\n#Context: Create route\n#Priority: Normal\n"
            "#Action: Execute\nBuild the bridge."
        )

        sent = dispatch("atp.send", {"atp_db_path": atp_db, "message": message})
        assert sent["status"] == "queued"
        assert sent["provenance_id"]
        message_id = sent["message_id"]

        queued = dispatch("atp.queue", {"atp_db_path": atp_db})
        assert queued["total"] == 1
        assert queued["messages"][0]["message_id"] == message_id

        route = dispatch(
            "atp.route",
            {
                "atp_db_path": atp_db,
                "db_path": db,
                "message_id": message_id,
                "required_capability": "llm_chat",
            },
        )
        assert route["route"]["agent_name"] == "Builder"
        assert route["route"]["routing_scope"] == "atp:execute:llm_chat"
        assert route["provenance_id"] == sent["provenance_id"]

        stored = dispatch(
            "atp.get_message", {"atp_db_path": atp_db, "message_id": message_id}
        )
        assert stored["status"] == "routed"
        assert stored["route"]["agent_name"] == "Builder"
        assert stored["provenance_id"] == sent["provenance_id"]

        assert "Build" in dispatch("atp.modes", {})["modes"]
        assert "Normal" in dispatch("atp.priorities", {})["priorities"]
        assert "Execute" in dispatch("atp.action_types", {})["action_types"]
        assert "#Mode:" in dispatch("atp.template", {})["template"]
        formatted = dispatch(
            "atp.format",
            {
                "mode": "Review",
                "context": "Check docs",
                "action_type": "Summarize",
                "content": "Review the bridge docs.",
            },
        )
        assert formatted["parsed"]["mode"] == "Review"


class TestTrustAndHebbianCommands:
    def test_trust_score_permissions_and_events(self, tmp_path):
        trust_db = str(tmp_path / "trust.db")
        payload = {"trust_db_path": trust_db, "entity_id": "alpha"}

        score = dispatch("trust.get_score", payload)
        assert score["entity_id"] == "alpha"
        assert score["level"] == "high"

        updated = dispatch("trust.set_score", {**payload, "score": 0.95})
        assert updated["level"] == "full"

        success = dispatch("trust.record_success", {**payload, "amount": 0.01})
        assert success["recorded"] == "success"

        before_zero = dispatch("trust.get_score", payload)["score"]
        zero_success = dispatch("trust.record_success", {**payload, "amount": 0.0})
        assert zero_success["score"] == pytest.approx(before_zero)

        zero_failure = dispatch("trust.record_failure", {**payload, "amount": 0.0})
        assert zero_failure["score"] == pytest.approx(before_zero)

        permissions = dispatch("trust.permissions", payload)
        assert "read" in permissions["permissions"]

        allowed = dispatch("trust.can_perform", {**payload, "operation": "read"})
        assert allowed["allowed"] is True

        report = dispatch("trust.report", {"trust_db_path": trust_db})
        assert report["total_entities"] >= 1

    def test_hebbian_weight_read_and_update(self, tmp_path):
        hebbian_db = str(tmp_path / "hebbian.db")
        updated = dispatch(
            "hebbian.update",
            {
                "hebbian_db_path": hebbian_db,
                "agent1": "Alpha",
                "agent2": "task:research",
                "delta": 2,
            },
        )
        assert updated["weight"] == 2

        weights = dispatch("hebbian.weights", {"hebbian_db_path": hebbian_db})
        assert weights["summary"]["total_connections"] == 1
        assert weights["connections"][0]["origin_node"] == "Alpha"

    def test_hebbian_sentinel_read_commands(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARTEMIS_HEBBIAN_SENTINEL_WINDOW", "4")
        monkeypatch.setenv("ARTEMIS_HEBBIAN_SENTINEL_WARMUP", "4")
        hebbian_db = str(tmp_path / "hebbian.db")
        manager = HebbianWeightManager(db_path=hebbian_db)
        for index, success in enumerate((True, False, True, False)):
            manager.record_outcome(
                "Alpha",
                f"task-{index}",
                success=success,
                performance=1.0 if success else 0.0,
                task_type="atp:execute:research",
            )

        status = dispatch(
            "hebbian.sentinel_status",
            {"hebbian_db_path": hebbian_db, "agent_name": "Alpha"},
        )
        alerts = dispatch(
            "hebbian.sentinel_alerts",
            {"hebbian_db_path": hebbian_db, "open_only": True},
        )

        assert status["signals"][0]["alert_active"] is True
        assert alerts["alerts"][0]["status"] == "open"


# ---------------------------------------------------------------------------
# governance.* commands
# ---------------------------------------------------------------------------
class TestGovernanceCommands:
    """Provide the TestGovernanceCommands abstraction used by this module."""

    def test_compute_trust_pristine(self, db):
        """Test that compute trust pristine.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch("governance.compute_trust", {"db_path": db, "name": "Alpha"})
        # No failures / no violations -> 1.0, and it's persisted.
        assert result["trust_score"] == pytest.approx(1.0)
        assert result["persisted"] is True
        assert "components" in result["breakdown"]

    def test_compute_trust_pulls_violation_count(self, db):
        # Record one violation, then compute without passing the count.
        """Test that compute trust pulls violation count.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "registry.record_violation",
            {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
        )
        result = dispatch(
            "governance.compute_trust",
            {"db_path": db, "name": "Alpha", "metrics": {}},
        )
        # security_score = 1 - 0.1*1 = 0.9 -> trust < 1.0
        assert result["trust_score"] < 1.0
        assert result["breakdown"]["components"]["security_score"] == pytest.approx(0.9)

    def test_compute_trust_persists_to_registry(self, db):
        """Test that compute trust persists to registry.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "governance.compute_trust",
            {
                "db_path": db,
                "name": "Alpha",
                "metrics": {"successful_executions": 5, "total_executions": 10},
            },
        )
        record = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert record["trust_score"] is not None

    def test_compute_trust_no_persist(self, db):
        """Test that compute trust no persist.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "governance.compute_trust",
            {"db_path": db, "name": "Alpha", "persist": False},
        )
        record = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert record["trust_score"] is None

    def test_compute_trust_unknown_agent(self, db):
        """Test that compute trust unknown agent.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("governance.compute_trust", {"db_path": db, "name": "ghost"})
        assert exc.value.code == "NOT_FOUND"

    def test_evaluate_update_auto(self, db):
        """Test that evaluate update auto.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "governance.evaluate_update",
            {
                "db_path": db,
                "agent_name": "Alpha",
                "trust_score": 0.95,
                "code_change_ratio": 0.005,
            },
        )
        assert result["tier"] == "auto"
        assert result["auto_approved"] is True
        assert result["trust_score"] == 0.95

    def test_evaluate_update_human_on_breaking(self, db):
        """Test that evaluate update human on breaking.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "governance.evaluate_update",
            {
                "db_path": db,
                "agent_name": "Alpha",
                "trust_score": 0.99,
                "breaking_changes": True,
            },
        )
        assert result["tier"] == "human"
        assert result["requires_human"] is True

    def test_evaluate_update_from_metrics(self, db):
        """Test that evaluate update from metrics.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "governance.evaluate_update",
            {
                "db_path": db,
                "agent_name": "Alpha",
                "metrics": {"successful_executions": 10, "total_executions": 10},
                "code_change_ratio": 0.0,
            },
        )
        # pristine metrics -> trust 1.0 -> auto
        assert result["tier"] == "auto"

    def test_evaluate_update_uses_persisted_trust(self, db):
        # Persist a low trust score, then evaluate with no trust/metrics.
        """Test that evaluate update uses persisted trust.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "governance.compute_trust",
            {
                "db_path": db,
                "name": "Alpha",
                "metrics": {
                    "successful_executions": 1,
                    "total_executions": 10,
                    "recent_violation_count": 5,
                },
            },
        )
        result = dispatch(
            "governance.evaluate_update", {"db_path": db, "agent_name": "Alpha"}
        )
        # Low persisted trust -> human tier
        assert result["tier"] == "human"

    def test_evaluate_update_no_trust_no_metrics_errors(self, db):
        """Test that evaluate update no trust no metrics errors.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "governance.evaluate_update", {"db_path": db, "agent_name": "Alpha"}
            )
        # Alpha has no persisted trust_score yet.
        assert exc.value.code == "INVALID_REQUEST"

    def test_checkpoint_round_trip_restores_registry_and_hebbian(self, db, tmp_path):
        checkpoint_dir = str(tmp_path / "checkpoints")
        hebbian_db = str(tmp_path / "hebbian_weights.db")
        trust_db = str(tmp_path / "trust_scores.db")
        payload = {
            "db_path": db,
            "hebbian_db_path": hebbian_db,
            "trust_db_path": trust_db,
            "checkpoint_dir": checkpoint_dir,
        }
        created = dispatch(
            "governance.checkpoints.create",
            {**payload, "metadata": {"reason": "test"}},
        )

        dispatch(
            "registry.record_violation",
            {**payload, "name": "Alpha", "violation_type": "rate_limit"},
        )
        dispatch(
            "hebbian.update",
            {
                **payload,
                "origin": "Alpha",
                "target": "task_type:research",
                "delta": 2.0,
            },
        )

        restored = dispatch(
            "governance.checkpoints.rollback",
            {
                **payload,
                "checkpoint_id": created["checkpoint_id"],
                "initiated_by": "test_operator",
                "confirmed": True,
            },
        )

        assert restored["status"] == "restored"
        agent = dispatch("registry.get_agent", {**payload, "name": "Alpha"})
        assert agent["violation_count"] == 0
        weights = dispatch("hebbian.weights", payload)
        assert weights["summary"]["total_connections"] == 0
        trust = dispatch("trust.get_score", {**payload, "entity_id": "Alpha"})
        assert trust["score"] == pytest.approx(agent["trust_score"])

    def test_rollback_requires_explicit_confirmation(self, db, tmp_path):
        payload = {
            "db_path": db,
            "checkpoint_dir": str(tmp_path / "checkpoints"),
        }
        created = dispatch("governance.checkpoints.create", payload)
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "governance.checkpoints.rollback",
                {
                    **payload,
                    "checkpoint_id": created["checkpoint_id"],
                    "initiated_by": "test_operator",
                },
            )
        assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# CLI round-trip — exercises the stdin/stdout envelope the TS layer uses
# ---------------------------------------------------------------------------
class TestCLI:
    """Provide the TestCLI abstraction used by this module."""

    def _run(self, request: dict, cwd):
        proc = subprocess.run(
            [sys.executable, "-m", "src.api_bridge"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        return proc

    def test_cli_success(self, db, repo_root):
        """Test that cli success.

        Args:
            db: Db value used by this operation.
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        proc = self._run(
            {"command": "registry.list_agents", "payload": {"db_path": db}},
            cwd=str(repo_root),
        )
        assert proc.returncode == 0
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["total"] == 1

    def test_cli_error_envelope(self, db, repo_root):
        """Test that cli error envelope.

        Args:
            db: Db value used by this operation.
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        proc = self._run(
            {"command": "registry.get_agent", "payload": {"db_path": db, "name": "x"}},
            cwd=str(repo_root),
        )
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is False
        assert envelope["code"] == "NOT_FOUND"

    def test_cli_missing_command(self, repo_root):
        """Test that cli missing command.

        Args:
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        proc = self._run({"payload": {}}, cwd=str(repo_root))
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["code"] == "INVALID_REQUEST"

    def test_cli_atp_parse_success(self, repo_root):
        proc = self._run(
            {
                "command": "atp.parse",
                "payload": {
                    "message": "#Mode: Build\n#Priority: Normal\n#Action: Execute"
                },
            },
            cwd=str(repo_root),
        )
        assert proc.returncode == 0
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["message"]["mode"] == "Build"
        assert envelope["data"]["message"]["priority"] == "Normal"
        assert envelope["data"]["message"]["action_type"] == "Execute"

    def test_cli_memory_write_traversal_error(self, repo_root, vault):
        proc = self._run(
            {
                "command": "memory.write",
                "payload": {
                    "vault_path": str(vault),
                    "path": "../escape.md",
                    "content": "blocked",
                },
            },
            cwd=str(repo_root),
        )
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is False
        assert envelope["code"] == "INVALID_REQUEST"
