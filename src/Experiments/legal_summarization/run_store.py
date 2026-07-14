"""Persistent storage for summarization runs, configs, and individual results.

Uses SQLite for structured queries and per-run Markdown reports for
human review — same dual-output pattern as the core RunLogger.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.runtime_paths import data_path, log_path


class RunStore:
    """Store and query summarization run results.

    Schema:
        **runs** — one row per batch invocation.
        **results** — one row per judgment summarized in a run.

    All data lives in a single SQLite file; Markdown reports are written
    alongside for quick human review.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        report_dir: Optional[str] = None,
    ):
        self.db_path = data_path(
            "legal_summarization.db",
            db_path,
            env_var="ARTEMIS_LEGAL_SUMMARIZATION_DB",
        )
        self.report_dir = Path(
            log_path(
                "legal_summarization",
                report_dir,
                env_var="ARTEMIS_LEGAL_SUMMARIZATION_LOG_DIR",
            )
        )

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id          TEXT PRIMARY KEY,
                    started_at      TEXT NOT NULL,
                    finished_at     TEXT,
                    status          TEXT NOT NULL DEFAULT 'running',
                    config_json     TEXT NOT NULL,
                    dataset_config  TEXT,
                    split           TEXT,
                    total_records   INTEGER DEFAULT 0,
                    completed       INTEGER DEFAULT 0,
                    failed          INTEGER DEFAULT 0,
                    duration_ms     REAL
                )
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT NOT NULL REFERENCES runs(run_id),
                    record_index    INTEGER NOT NULL,
                    input_preview   TEXT,
                    reference_summary TEXT,
                    generated_summary TEXT,
                    mode            TEXT,
                    status          TEXT NOT NULL,
                    inference_ms    REAL,
                    input_chars     INTEGER,
                    output_chars    INTEGER,
                    created_at      REAL NOT NULL
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(
        self,
        run_id: str,
        config_json: str,
        dataset_config: str,
        split: str,
        total_records: int,
    ) -> None:
        """Start run.

        Args:
            run_id (str): Identifier of the run being queried or updated.
            config_json (str): Serialized configuration payload for the run.
            dataset_config (str): Dataset configuration identifier for the summarization run.
            split (str): Dataset split name to process.
            total_records (int): Total number of records expected in the run.

        Returns:
            None: This function does not return a value.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO runs
                   (run_id, started_at, status, config_json, dataset_config, split, total_records)
                   VALUES (?, ?, 'running', ?, ?, ?, ?)""",
                (
                    run_id,
                    datetime.now().isoformat(),
                    config_json,
                    dataset_config,
                    split,
                    total_records,
                ),
            )
            conn.commit()

    def finish_run(self, run_id: str, status: str, duration_ms: float) -> None:
        """Finish run.

        Args:
            run_id (str): Identifier of the run being queried or updated.
            status (str): Status value to persist or return.
            duration_ms (float): Duration ms value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with sqlite3.connect(self.db_path) as conn:
            # Count completed / failed from results table
            completed = conn.execute(
                "SELECT COUNT(*) FROM results WHERE run_id = ? AND status = 'success'",
                (run_id,),
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM results WHERE run_id = ? AND status != 'success'",
                (run_id,),
            ).fetchone()[0]
            conn.execute(
                """UPDATE runs
                   SET finished_at = ?, status = ?, duration_ms = ?,
                       completed = ?, failed = ?
                   WHERE run_id = ?""",
                (
                    datetime.now().isoformat(),
                    status,
                    duration_ms,
                    completed,
                    failed,
                    run_id,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Result storage
    # ------------------------------------------------------------------

    def store_result(
        self,
        run_id: str,
        record_index: int,
        input_text: str,
        reference_summary: str,
        generated_summary: str,
        mode: str,
        status: str,
        inference_ms: float,
    ) -> None:
        """Store result.

        Args:
            run_id (str): Identifier of the run being queried or updated.
            record_index (int): Position of the record within the run.
            input_text (str): Input text associated with the stored result.
            reference_summary (str): Reference summary value used by this operation.
            generated_summary (str): Generated summary value used by this operation.
            mode (str): Execution or summarization mode to apply.
            status (str): Status value to persist or return.
            inference_ms (float): Inference ms value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        preview = input_text[:300] + "..." if len(input_text) > 300 else input_text
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO results
                   (run_id, record_index, input_preview, reference_summary,
                    generated_summary, mode, status, inference_ms,
                    input_chars, output_chars, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    record_index,
                    preview,
                    reference_summary,
                    generated_summary,
                    mode,
                    status,
                    inference_ms,
                    len(input_text),
                    len(generated_summary),
                    time.time(),
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_runs(self, limit: int = 20) -> list[dict]:
        """List runs.

        Args:
            limit (int): Maximum number of records to return or process.

        Returns:
            list[dict]: List containing the resulting items.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> Optional[dict]:
        """Return run.

        Args:
            run_id (str): Identifier of the run being queried or updated.

        Returns:
            Optional[dict]: Matching value when available; otherwise None.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_results(self, run_id: str, limit: int = 500) -> list[dict]:
        """Return results.

        Args:
            run_id (str): Identifier of the run being queried or updated.
            limit (int): Maximum number of records to return or process.

        Returns:
            list[dict]: List containing the resulting items.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM results WHERE run_id = ? ORDER BY record_index LIMIT ?",
                (run_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def compare_runs(self, run_ids: list[str]) -> list[dict]:
        """Return side-by-side run metadata for comparison.

        Args:
            run_ids (list[str]): Run identifiers to fetch for comparison.

        Returns:
            list[dict]: Run metadata records for the identifiers that were found.
        """
        runs = []
        for rid in run_ids:
            r = self.get_run(rid)
            if r:
                runs.append(r)
        return runs

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------

    def write_report(self, run_id: str) -> Path:
        """Generate a Markdown report for a completed run.

        Args:
            run_id (str): Identifier of the run being queried or updated.

        Returns:
            Path: Resolved path produced by the operation.
        """
        run = self.get_run(run_id)
        results = self.get_results(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        report_path = self.report_dir / f"run_{run_id}.md"
        config = json.loads(run["config_json"]) if run["config_json"] else {}

        lines = [
            f"# Legal Summarization Run: {run_id}",
            "",
            f"**Status:** {run['status']}  ",
            f"**Started:** {run['started_at']}  ",
            f"**Finished:** {run.get('finished_at', 'N/A')}  ",
            f"**Duration:** {run.get('duration_ms', 0):.0f} ms  ",
            f"**Dataset:** {run['dataset_config']} / {run['split']}  ",
            f"**Records:** {run['completed']} completed, {run['failed']} failed "
            f"of {run['total_records']} total",
            "",
            "## Configuration",
            "",
            "```json",
            json.dumps(config, indent=2),
            "```",
            "",
            "## Results",
            "",
            "| # | Status | Mode | Input Chars | Output Chars | Inference ms |",
            "|---|--------|------|-------------|--------------|--------------|",
        ]

        for r in results:
            lines.append(
                f"| {r['record_index']} | {r['status']} | {r['mode']} "
                f"| {r['input_chars']} | {r['output_chars']} "
                f"| {r.get('inference_ms', 0):.0f} |"
            )

        # Sample outputs (first 3)
        if results:
            lines.append("")
            lines.append("## Sample Summaries")
            for r in results[:3]:
                lines.append("")
                lines.append(f"### Record {r['record_index']}")
                lines.append("")
                lines.append("**Generated:**")
                lines.append(f"> {(r['generated_summary'] or '')[:500]}")
                if r.get("reference_summary"):
                    lines.append("")
                    lines.append("**Reference:**")
                    lines.append(f"> {r['reference_summary'][:500]}")

        lines.append("")
        lines.append(f"---\n*Report generated at {datetime.now().isoformat()}*")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
