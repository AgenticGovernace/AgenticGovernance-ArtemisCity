"""Behavioral coverage for the canonical run logger.

These tests deliberately use temporary log and data roots.  Besides keeping
the repository clean, that makes the SQLite audit trail and its Markdown
mirror independently inspectable in every test.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.utils import run_logger as run_logger_module
from src.utils.run_logger import (RunLogger, get_recent_runs, get_run_events,
                                  get_run_logger, init_run_logger)


@pytest.fixture(autouse=True)
def _isolate_global_run_logger(monkeypatch: pytest.MonkeyPatch):
    """Prevent a process-global logger from leaking between tests."""
    monkeypatch.setattr(run_logger_module, "_run_logger", None)


def _logger(tmp_path: Path, run_id: str = "coverage-run") -> RunLogger:
    return RunLogger(
        log_dir=str(tmp_path / "logs"),
        db_path=str(tmp_path / "data" / "run_logs.db"),
        run_id=run_id,
    )


def test_global_logger_is_lazy_and_explicit_initialization_replaces_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ARTEMIS_LOG_DIR", str(tmp_path / "default-logs"))
    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "default-data"))

    lazy = get_run_logger()
    assert get_run_logger() is lazy
    assert lazy.md_path.parent == tmp_path / "default-logs"
    assert Path(lazy.db_path) == tmp_path / "default-data" / "run_logs.db"

    replacement = init_run_logger(
        log_dir=str(tmp_path / "replacement-logs"),
        db_path=str(tmp_path / "replacement-data" / "runs.db"),
        run_id="replacement",
    )
    assert replacement is get_run_logger()
    assert replacement is not lazy
    assert replacement.run_id == "replacement"


def test_initialization_migrates_legacy_event_table(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                component TEXT NOT NULL,
                message TEXT,
                metadata TEXT,
                duration_ms REAL,
                created_at REAL NOT NULL
            )
            """)

    logger = RunLogger(
        log_dir=str(tmp_path / "logs"),
        db_path=str(db_path),
        run_id="legacy",
    )

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(event_log)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(event_log)")}

    assert {"prov_id", "parent_prov_id"} <= columns
    assert "idx_event_prov" in indexes
    assert logger.get_run_stats() == {
        "run_id": "legacy",
        "event_count": 1,
        "vector_operations": 0,
        "db_writes": 0,
    }


def test_markdown_helpers_escape_rows_append_sections_and_surface_failures(
    tmp_path: Path,
):
    logger = _logger(tmp_path)
    logger._append_md_row("12:00", "component", "event", "a|b\nnext")
    logger._append_md_section("## Extra section")

    markdown = logger.md_path.read_text(encoding="utf-8")
    assert "a\\|b next" in markdown
    assert "## Extra section" in markdown

    # SQLite is the durable audit sink.  If its Markdown mirror becomes
    # unwritable, the caller sees the failure while the event remains durable.
    logger.md_path = tmp_path / "not-a-file"
    logger.md_path.mkdir()
    with pytest.raises(IsADirectoryError):
        logger.log_event("mirror_failure", "tests", message="cannot append")

    with sqlite3.connect(logger.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE event_type = 'mirror_failure'"
        ).fetchone()[0]
    assert count == 1


def test_log_event_persists_details_and_rejects_duplicate_provenance(tmp_path: Path):
    logger = _logger(tmp_path)
    prov_id = logger.log_event(
        "custom",
        "coverage",
        metadata={"one": 1, "two": 2, "three": 3, "ignored": 4},
        message="message with | pipe",
        duration_ms=12.5,
        prov_id="stable-provenance",
        parent_prov_id="parent-provenance",
    )
    assert prov_id == "stable-provenance"

    event = get_run_events(logger.db_path, logger.run_id, "custom")[0]
    assert event["metadata"] == {"one": 1, "two": 2, "three": 3, "ignored": 4}
    assert event["parent_prov_id"] == "parent-provenance"
    assert "message with \\| pipe" in logger.md_path.read_text(encoding="utf-8")

    with pytest.raises(sqlite3.IntegrityError):
        logger.log_event("duplicate", "coverage", prov_id="stable-provenance")


def test_vector_and_database_write_logs_capture_both_preview_shapes(tmp_path: Path):
    logger = _logger(tmp_path)
    logger.log_vector_operation(
        "long-doc",
        "upsert",
        "x" * 101,
        [float(index) for index in range(12)],
        metadata={"source": "test"},
        latency_ms=4.2,
    )
    logger.log_vector_operation("short-doc", "delete", "short", [1.0, 2.0])

    logger.log_db_write(
        "/tmp/main.db",
        "records",
        "UPSERT",
        record_id="record-1",
        data={f"field-{index}": "v" * 100 for index in range(6)},
        rows_affected=2,
        latency_ms=2.5,
    )
    logger.log_db_write("plain.db", "records", "DELETE", data=None)

    with sqlite3.connect(logger.db_path) as conn:
        long_vector = conn.execute("""
            SELECT content_preview, embedding_dim, embedding_sample, metadata
            FROM vector_log WHERE doc_id = 'long-doc'
            """).fetchone()
        short_vector = conn.execute(
            "SELECT content_preview, embedding_sample FROM vector_log "
            "WHERE doc_id = 'short-doc'"
        ).fetchone()
        writes = conn.execute(
            "SELECT data_preview FROM db_write_log ORDER BY id"
        ).fetchall()

    assert long_vector[0] == "x" * 100 + "..."
    assert long_vector[1] == 12
    assert json.loads(long_vector[2]) == [
        0.0,
        1.0,
        2.0,
        3.0,
        4.0,
        "...",
        7.0,
        8.0,
        9.0,
        10.0,
        11.0,
    ]
    assert json.loads(long_vector[3]) == {"source": "test"}
    assert short_vector == ("short", "[1.0, 2.0]")
    assert len(writes[0][0]) == 203
    assert writes[0][0].endswith("...")
    assert writes[1][0] is None
    assert logger.get_run_stats() == {
        "run_id": "coverage-run",
        "event_count": 5,
        "vector_operations": 2,
        "db_writes": 2,
    }


def test_specialized_log_helpers_preserve_context(tmp_path: Path):
    logger = _logger(tmp_path)
    logger.log_task_execution(
        "task-1",
        "Research Agent",
        "completed",
        9.5,
        metadata={"attempt": 2},
        prov_id="task-prov",
        parent_prov_id="prompt-prov",
    )
    logger.log_task_execution("task-2", "LLM Agent", "failed", 1.0)
    logger.log_hebbian_update("Research Agent", "summary", "strengthen", 0.5, 0.8)
    logger.log_memory_bus_operation(
        "write",
        "Agent Outputs/report.md",
        "success",
        vector_latency_ms=2.0,
        file_latency_ms=1.0,
        total_latency_ms=3.0,
        metadata={"atomic": True},
    )
    logger.log_memory_bus_operation("read", "Agent Inputs/task.md", "miss")

    task = get_run_events(logger.db_path, logger.run_id, "task_completed")[0]
    hebbian = get_run_events(logger.db_path, logger.run_id, "hebbian_strengthen")[0]
    memory = get_run_events(logger.db_path, logger.run_id, "memory_bus_write")[0]

    assert task["prov_id"] == "task-prov"
    assert task["parent_prov_id"] == "prompt-prov"
    assert task["metadata"]["attempt"] == 2
    assert hebbian["metadata"]["delta"] == pytest.approx(0.3)
    assert memory["metadata"] == {
        "path": "Agent Outputs/report.md",
        "status": "success",
        "vector_latency_ms": 2.0,
        "file_latency_ms": 1.0,
        "total_latency_ms": 3.0,
        "atomic": True,
    }

    with sqlite3.connect(logger.db_path) as conn:
        mirror = conn.execute("""
            SELECT operation, record_id, data_preview
            FROM db_write_log WHERE table_name = 'node_connections'
            """).fetchone()
    assert mirror[0:2] == ("UPSERT", "Research Agent→summary")
    assert json.loads(mirror[2]) == {"weight": 0.8, "operation": "strengthen"}


def test_timed_operation_logs_success_and_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    logger = _logger(tmp_path)

    ticks = iter((10.0, 10.25, 20.0, 20.5))
    monkeypatch.setattr(run_logger_module.time, "perf_counter", lambda: next(ticks))

    with logger.timed_operation(
        "timed_success", "worker", {"input": "value"}
    ) as operation:
        operation["status"] = "cached"
        operation["message"] = "cache hit"

    with pytest.raises(ValueError, match="original failure"):
        with logger.timed_operation("timed_error", "worker") as operation:
            operation["metadata"] = ["invalid metadata shape"]
            operation["message"] = 42
            raise ValueError("original failure")

    success = get_run_events(logger.db_path, logger.run_id, "timed_success")[0]
    failure = get_run_events(logger.db_path, logger.run_id, "timed_error")[0]
    assert success["message"] == "cache hit"
    assert success["metadata"] == {"input": "value", "status": "cached"}
    assert failure["message"] is None
    assert failure["metadata"] == {"status": "error"}

    with sqlite3.connect(logger.db_path) as conn:
        durations = dict(
            conn.execute(
                "SELECT event_type, duration_ms FROM event_log "
                "WHERE event_type LIKE 'timed_%'"
            ).fetchall()
        )
    assert durations == {"timed_success": 250.0, "timed_error": 500.0}


def test_finalize_run_writes_counts_breakdown_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    logger = _logger(tmp_path)
    logger.log_vector_operation("doc", "query", "text", [0.1])
    logger.log_db_write("state.db", "items", "INSERT")
    logger.run_start_time = 100.0
    monkeypatch.setattr(run_logger_module.time, "perf_counter", lambda: 100.125)

    logger.finalize_run("failed", {"reason": "expected test outcome"})

    stats = logger.get_run_stats()
    assert stats == {
        "run_id": "coverage-run",
        "event_count": 4,
        "vector_operations": 1,
        "db_writes": 1,
    }
    run_end = get_run_events(logger.db_path, logger.run_id, "run_end")[0]
    assert run_end["metadata"]["status"] == "failed"
    assert run_end["metadata"]["reason"] == "expected test outcome"
    assert run_end["metadata"]["total_events"] == 3

    markdown = logger.md_path.read_text(encoding="utf-8")
    assert "## Run Summary" in markdown
    assert "| **Status** | failed |" in markdown
    assert "| **Duration** | 125.00 ms |" in markdown
    assert "| **Vector Operations** | 1 |" in markdown
    assert "- **run_end**: 1" in markdown


def test_recent_runs_and_event_queries_handle_filters_limits_and_bad_json(
    tmp_path: Path,
):
    db_path = tmp_path / "run_logs.db"
    first = RunLogger(str(tmp_path / "logs"), str(db_path), "first")
    first.log_event("alpha", "tests", metadata={"valid": True})
    first.log_event("beta", "tests", metadata={"valid": True})
    second = RunLogger(str(tmp_path / "logs"), str(db_path), "second")
    second.log_event("alpha", "tests", metadata={"order": 2})

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE event_log SET metadata = '{bad json' "
            "WHERE run_id = 'first' AND event_type = 'beta'"
        )
        conn.execute(
            """
            INSERT INTO event_log (
                run_id, timestamp, event_type, component, message, metadata,
                duration_ms, prov_id, parent_prov_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "string-time",
                "not-an-iso-time",
                "manual",
                "tests",
                None,
                None,
                None,
                "manual-prov",
                None,
                "unknown-time",
            ),
        )
        conn.commit()

    recent = get_recent_runs(str(db_path), limit=10)
    by_id = {run["run_id"]: run for run in recent}
    assert set(by_id) == {"first", "second", "string-time"}
    assert "T" in by_id["first"]["start_time"]
    assert by_id["string-time"]["start_time"] == "unknown-time"
    assert len(get_recent_runs(str(db_path), limit=1)) == 1

    alpha = get_run_events(str(db_path), "first", "alpha", limit=1)
    all_first = get_run_events(str(db_path), "first", limit=10)
    beta = next(event for event in all_first if event["event_type"] == "beta")
    assert len(alpha) == 1
    assert alpha[0]["metadata"] == {"valid": True}
    assert beta["metadata"] == "{bad json"
    assert get_run_events(str(db_path), "missing") == []


def test_query_helpers_surface_missing_schema_errors(tmp_path: Path):
    missing_schema = tmp_path / "empty.db"
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        get_recent_runs(str(missing_schema))
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        get_run_events(str(missing_schema), "run")
