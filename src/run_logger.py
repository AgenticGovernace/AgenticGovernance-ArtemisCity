"""
Run Logger for Artemis City MCP

Provides comprehensive logging with:
- Markdown file output for each run (human-readable audit trail)
- SQLite table for semantic vector logging
- Structured event tracking for all database operations
"""

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager


class RunLogger:
    """
    Comprehensive run logger that writes to both Markdown files and SQLite.

    Features:
    - Per-run markdown log files with timestamps
    - Vector embedding log table for semantic tracking
    - Event log table for all operations (DB writes, task execution, etc.)
    - Structured JSON metadata for each event
    """

    def __init__(
        self,
        log_dir: str = "logs",
        db_path: str = "data/run_logs.db",
        run_id: Optional[str] = None,
    ):
        self.log_dir = Path(log_dir)
        self.db_path = db_path
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_start_time = time.perf_counter()
        self._events: List[Dict] = []

        # Ensure directories exist
        self.log_dir.mkdir(parents=True, exist_ok=True)
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # Initialize database
        self._initialize_database()

        # Initialize markdown file
        self.md_path = self.log_dir / f"run_{self.run_id}.md"
        self._write_md_header()

        # Log run start
        self.log_event("run_start", "system", {"run_id": self.run_id})

    def _initialize_database(self):
        """Create logging tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # Event log table - tracks all operations
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_log (
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
            """
            )

            # Vector log table - tracks all semantic embeddings
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    content_preview TEXT,
                    embedding_dim INTEGER,
                    embedding_sample TEXT,
                    metadata TEXT,
                    latency_ms REAL,
                    created_at REAL NOT NULL
                )
            """
            )

            # Database write log - tracks all DB operations
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS db_write_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    database TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    record_id TEXT,
                    data_preview TEXT,
                    rows_affected INTEGER,
                    latency_ms REAL,
                    created_at REAL NOT NULL
                )
            """
            )

            # Create indexes for efficient querying
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_run ON event_log(run_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vector_run ON vector_log(run_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vector_doc ON vector_log(doc_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dbwrite_run ON db_write_log(run_id)"
            )

            conn.commit()

    def _write_md_header(self):
        """Write the markdown file header."""
        header = f"""# MCP Run Log: {self.run_id}

**Run Started:** {datetime.now().isoformat()}
**Log File:** `{self.md_path}`
**Database:** `{self.db_path}`

---

## Run Events

| Timestamp | Component | Event | Details |
|-----------|-----------|-------|---------|
"""
        with open(self.md_path, "w", encoding="utf-8") as f:
            f.write(header)

    def _append_md_row(
        self, timestamp: str, component: str, event_type: str, details: str
    ):
        """Append a row to the markdown event table."""
        # Escape pipe characters in details
        details_escaped = details.replace("|", "\\|").replace("\n", " ")
        row = f"| {timestamp} | {component} | {event_type} | {details_escaped} |\n"
        with open(self.md_path, "a", encoding="utf-8") as f:
            f.write(row)

    def _append_md_section(self, section: str):
        """Append a new section to the markdown file."""
        with open(self.md_path, "a", encoding="utf-8") as f:
            f.write(f"\n{section}\n")

    def log_event(
        self,
        event_type: str,
        component: str,
        metadata: Optional[Dict] = None,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ):
        """
        Log a general event.

        Args:
            event_type: Type of event (e.g., 'task_start', 'db_write', 'error')
            component: Component name (e.g., 'orchestrator', 'memory_bus')
            metadata: Additional structured data
            message: Human-readable message
            duration_ms: Operation duration if applicable
        """
        timestamp = datetime.now().isoformat()
        created_at = time.time()

        event = {
            "run_id": self.run_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "component": component,
            "message": message,
            "metadata": metadata,
            "duration_ms": duration_ms,
            "created_at": created_at,
        }
        self._events.append(event)

        # Write to SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO event_log
                (run_id, timestamp, event_type, component, message, metadata, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self.run_id,
                    timestamp,
                    event_type,
                    component,
                    message,
                    json.dumps(metadata) if metadata else None,
                    duration_ms,
                    created_at,
                ),
            )
            conn.commit()

        # Write to markdown
        details = message or ""
        if metadata:
            key_info = ", ".join(f"{k}={v}" for k, v in list(metadata.items())[:3])
            details = f"{details} ({key_info})" if details else key_info

        self._append_md_row(
            timestamp.split("T")[1][:12],  # Just time portion
            component,
            event_type,
            details[:100],  # Truncate for table readability
        )

    def log_vector_operation(
        self,
        doc_id: str,
        operation: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict] = None,
        latency_ms: Optional[float] = None,
    ):
        """
        Log a vector store operation.

        Args:
            doc_id: Document identifier
            operation: Operation type ('upsert', 'query', 'delete')
            content: Document content
            embedding: The embedding vector
            metadata: Additional metadata
            latency_ms: Operation latency
        """
        timestamp = datetime.now().isoformat()
        created_at = time.time()

        # Create content preview (first 100 chars)
        content_preview = content[:100] + "..." if len(content) > 100 else content

        # Sample embedding (first 5 and last 5 values)
        if len(embedding) > 10:
            embedding_sample = embedding[:5] + ["..."] + embedding[-5:]
        else:
            embedding_sample = embedding

        # Write to SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO vector_log
                (run_id, timestamp, doc_id, operation, content_preview,
                 embedding_dim, embedding_sample, metadata, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self.run_id,
                    timestamp,
                    doc_id,
                    operation,
                    content_preview,
                    len(embedding),
                    json.dumps(embedding_sample),
                    json.dumps(metadata) if metadata else None,
                    latency_ms,
                    created_at,
                ),
            )
            conn.commit()

        # Log as event too
        self.log_event(
            f"vector_{operation}",
            "vector_store",
            {
                "doc_id": doc_id,
                "embedding_dim": len(embedding),
                "content_length": len(content),
            },
            f"Vector {operation}: {doc_id}",
            latency_ms,
        )

    def log_db_write(
        self,
        database: str,
        table_name: str,
        operation: str,
        record_id: Optional[str] = None,
        data: Optional[Dict] = None,
        rows_affected: int = 1,
        latency_ms: Optional[float] = None,
    ):
        """
        Log a database write operation.

        Args:
            database: Database name/path
            table_name: Table being written to
            operation: Operation type ('INSERT', 'UPDATE', 'DELETE', 'UPSERT')
            record_id: Primary key or identifier of record
            data: Data being written (will be previewed)
            rows_affected: Number of rows affected
            latency_ms: Operation latency
        """
        timestamp = datetime.now().isoformat()
        created_at = time.time()

        # Create data preview
        data_preview = None
        if data:
            preview_items = list(data.items())[:5]
            data_preview = json.dumps(dict(preview_items))
            if len(data_preview) > 200:
                data_preview = data_preview[:200] + "..."

        # Write to SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO db_write_log
                (run_id, timestamp, database, table_name, operation,
                 record_id, data_preview, rows_affected, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self.run_id,
                    timestamp,
                    database,
                    table_name,
                    operation,
                    record_id,
                    data_preview,
                    rows_affected,
                    latency_ms,
                    created_at,
                ),
            )
            conn.commit()

        # Log as event too
        self.log_event(
            "db_write",
            database.split("/")[-1],  # Just filename
            {
                "table": table_name,
                "operation": operation,
                "record_id": record_id,
                "rows_affected": rows_affected,
            },
            f"{operation} on {table_name}",
            latency_ms,
        )

    def log_task_execution(
        self,
        task_id: str,
        agent_name: str,
        status: str,
        duration_ms: float,
        metadata: Optional[Dict] = None,
    ):
        """Log task execution details."""
        self.log_event(
            f"task_{status}",
            "orchestrator",
            {
                "task_id": task_id,
                "agent": agent_name,
                "duration_ms": duration_ms,
                **(metadata or {}),
            },
            f"Task {task_id} {status} by {agent_name}",
            duration_ms,
        )

    def log_hebbian_update(
        self,
        origin: str,
        target: str,
        operation: str,
        old_weight: float,
        new_weight: float,
        latency_ms: Optional[float] = None,
    ):
        """Log Hebbian weight updates."""
        self.log_event(
            f"hebbian_{operation}",
            "hebbian_weights",
            {
                "origin": origin,
                "target": target,
                "old_weight": old_weight,
                "new_weight": new_weight,
                "delta": new_weight - old_weight,
            },
            f"Hebbian {operation}: {origin} → {target} ({old_weight:.1f} → {new_weight:.1f})",
            latency_ms,
        )

        # Also log as DB write
        self.log_db_write(
            "hebbian_weights.db",
            "node_connections",
            "UPSERT",
            f"{origin}→{target}",
            {"weight": new_weight, "operation": operation},
            latency_ms=latency_ms,
        )

    def log_memory_bus_operation(
        self,
        operation: str,
        path: str,
        status: str,
        vector_latency_ms: Optional[float] = None,
        file_latency_ms: Optional[float] = None,
        total_latency_ms: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ):
        """Log memory bus operations."""
        self.log_event(
            f"memory_bus_{operation}",
            "memory_bus",
            {
                "path": path,
                "status": status,
                "vector_latency_ms": vector_latency_ms,
                "file_latency_ms": file_latency_ms,
                "total_latency_ms": total_latency_ms,
                **(metadata or {}),
            },
            f"Memory bus {operation}: {path} ({status})",
            total_latency_ms,
        )

    @contextmanager
    def timed_operation(
        self, event_type: str, component: str, metadata: Optional[Dict] = None
    ):
        """
        Context manager for timing operations.

        Usage:
            with run_logger.timed_operation("task_execution", "orchestrator") as op:
                # do work
                op["result"] = "success"
        """
        start = time.perf_counter()
        context = {"metadata": metadata or {}}
        try:
            yield context
            status = context.get("status", "success")
        except Exception as e:
            status = "error"
            context["error"] = str(e)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.log_event(
                event_type,
                component,
                {**context.get("metadata", {}), "status": status},
                context.get("message"),
                duration_ms,
            )

    def finalize_run(self, status: str = "completed", summary: Optional[Dict] = None):
        """
        Finalize the run log with summary statistics.

        Args:
            status: Final run status
            summary: Optional summary data
        """
        run_duration_ms = (time.perf_counter() - self.run_start_time) * 1000

        # Log run end event
        self.log_event(
            "run_end",
            "system",
            {
                "run_id": self.run_id,
                "status": status,
                "duration_ms": run_duration_ms,
                "total_events": len(self._events),
                **(summary or {}),
            },
            f"Run {status} after {run_duration_ms:.0f}ms",
        )

        # Get statistics from database
        with sqlite3.connect(self.db_path) as conn:
            event_count = conn.execute(
                "SELECT COUNT(*) FROM event_log WHERE run_id = ?", (self.run_id,)
            ).fetchone()[0]

            vector_count = conn.execute(
                "SELECT COUNT(*) FROM vector_log WHERE run_id = ?", (self.run_id,)
            ).fetchone()[0]

            db_write_count = conn.execute(
                "SELECT COUNT(*) FROM db_write_log WHERE run_id = ?", (self.run_id,)
            ).fetchone()[0]

        # Write summary section to markdown
        summary_md = f"""
---

## Run Summary

| Metric | Value |
|--------|-------|
| **Run ID** | {self.run_id} |
| **Status** | {status} |
| **Duration** | {run_duration_ms:.2f} ms |
| **Total Events** | {event_count} |
| **Vector Operations** | {vector_count} |
| **DB Writes** | {db_write_count} |

### Event Types Breakdown

"""

        # Get event type breakdown
        with sqlite3.connect(self.db_path) as conn:
            breakdown = conn.execute(
                """
                SELECT event_type, COUNT(*) as count
                FROM event_log
                WHERE run_id = ?
                GROUP BY event_type
                ORDER BY count DESC
            """,
                (self.run_id,),
            ).fetchall()

        for event_type, count in breakdown:
            summary_md += f"- **{event_type}**: {count}\n"

        summary_md += f"\n---\n\n*Log generated at {datetime.now().isoformat()}*\n"

        self._append_md_section(summary_md)

    def get_run_stats(self) -> Dict:
        """Get statistics for the current run."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            stats = {
                "run_id": self.run_id,
                "event_count": conn.execute(
                    "SELECT COUNT(*) FROM event_log WHERE run_id = ?", (self.run_id,)
                ).fetchone()[0],
                "vector_operations": conn.execute(
                    "SELECT COUNT(*) FROM vector_log WHERE run_id = ?", (self.run_id,)
                ).fetchone()[0],
                "db_writes": conn.execute(
                    "SELECT COUNT(*) FROM db_write_log WHERE run_id = ?", (self.run_id,)
                ).fetchone()[0],
            }

            return stats


# Global run logger instance (initialized on import or explicitly)
_run_logger: Optional[RunLogger] = None


def get_run_logger() -> RunLogger:
    """Get or create the global run logger instance."""
    global _run_logger
    if _run_logger is None:
        _run_logger = RunLogger()
    return _run_logger


def init_run_logger(
    log_dir: str = "logs",
    db_path: str = "data/run_logs.db",
    run_id: Optional[str] = None,
) -> RunLogger:
    """Initialize a new run logger (resets the global instance)."""
    global _run_logger
    _run_logger = RunLogger(log_dir=log_dir, db_path=db_path, run_id=run_id)
    return _run_logger


def get_recent_runs(db_path: str = "data/run_logs.db", limit: int = 20) -> List[Dict]:
    """
    Get recent runs with summary statistics.

    Args:
        db_path: Path to run_logs database
        limit: Maximum number of runs to return

    Returns:
        List of run summaries
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT DISTINCT run_id,
                   MIN(created_at) as start_time,
                   MAX(created_at) as end_time,
                   COUNT(*) as total_events
            FROM event_log
            GROUP BY run_id
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (limit,)
        )
        runs = []
        for row in cursor.fetchall():
            run_dict = dict(row)
            # Convert timestamps to ISO format
            start = run_dict['start_time']
            end = run_dict['end_time']
            run_dict['start_time'] = datetime.fromtimestamp(start).isoformat() if isinstance(start, (int, float)) else str(start)
            run_dict['end_time'] = datetime.fromtimestamp(end).isoformat() if isinstance(end, (int, float)) else str(end)
            runs.append(run_dict)
        return runs


def get_run_events(db_path: str = "data/run_logs.db", run_id: str = None, event_type: str = None, limit: int = 100) -> List[Dict]:
    """
    Get events for a specific run, optionally filtered by event type.

    Args:
        db_path: Path to run_logs database
        run_id: Run ID to query
        event_type: Optional event type filter
        limit: Maximum number of events to return

    Returns:
        List of event dictionaries
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        if event_type:
            cursor = conn.execute(
                """
                SELECT run_id, timestamp, event_type, component, message, metadata
                FROM event_log
                WHERE run_id = ? AND event_type = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (run_id, event_type, limit)
            )
        else:
            cursor = conn.execute(
                """
                SELECT run_id, timestamp, event_type, component, message, metadata
                FROM event_log
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (run_id, limit)
            )

        events = []
        for row in cursor.fetchall():
            event_dict = dict(row)
            # Parse metadata JSON if present
            if event_dict['metadata']:
                try:
                    event_dict['metadata'] = json.loads(event_dict['metadata'])
                except:
                    pass
            events.append(event_dict)
        return events
