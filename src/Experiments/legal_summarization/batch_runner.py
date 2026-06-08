"""Batch runner — orchestrates summarization across a dataset slice.

Wires together: LegalDatasetLoader -> LegalSummarizerAgent -> RunStore,
with progress reporting through the core RunLogger.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

try:
    from .dataset_loader import JudgmentRecord, LegalDatasetLoader
    from .legal_summarizer_agent import LegalSummarizerAgent
    from .run_store import RunStore
    from .summarization_config import AggregationLevel, SummarizationConfig
except ImportError:
    from dataset_loader import JudgmentRecord, LegalDatasetLoader
    from legal_summarizer_agent import LegalSummarizerAgent
    from run_store import RunStore
    from summarization_config import AggregationLevel, SummarizationConfig

logger = logging.getLogger("legal_summarization.batch_runner")


class BatchRunner:
    """Execute a parameterized summarization run over legal judgments.

    Usage::

        config = SummarizationConfig(dataset_config="summary_en", limit=50)
        runner = BatchRunner()
        report = runner.run(config)
        print(report)
    """

    def __init__(
        self,
        loader: Optional[LegalDatasetLoader] = None,
        agent: Optional[LegalSummarizerAgent] = None,
        store: Optional[RunStore] = None,
        run_logger=None,
    ):
        self.loader = loader or LegalDatasetLoader()
        self.agent = agent or LegalSummarizerAgent()
        self.store = store or RunStore()
        self._run_logger = run_logger  # Optional core RunLogger for event integration

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, config: Optional[SummarizationConfig] = None) -> dict:
        """Execute a full summarization run.

        Returns:
            dict with run_id, status, completed, failed, duration_ms, report_path.

        Args:
            config (Optional[SummarizationConfig]): Configuration payload used to control
                behavior.
        """
        config = config or SummarizationConfig()
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        logger.info("=== Starting legal summarization run %s ===", run_id)
        logger.info(
            "Config: dataset=%s split=%s mode=%s audience=%s limit=%s",
            config.dataset_config,
            config.split,
            config.mode.value,
            config.audience.value,
            config.limit,
        )

        # Load dataset
        records = self.loader.load(
            config=config.dataset_config,
            split=config.split,
            limit=config.limit,
        )

        if not records:
            logger.warning("No records loaded — aborting run.")
            return {
                "run_id": run_id,
                "status": "empty",
                "completed": 0,
                "failed": 0,
                "duration_ms": 0,
            }

        # Register run
        self.store.start_run(
            run_id=run_id,
            config_json=config.to_json(),
            dataset_config=config.dataset_config,
            split=config.split,
            total_records=len(records),
        )

        if self._run_logger:
            self._run_logger.log_event(
                "legal_summarization_start",
                "batch_runner",
                {"run_id": run_id, "total_records": len(records)},
                f"Legal summarization run {run_id} started with {len(records)} records",
            )

        # Dispatch based on aggregation level
        start = time.perf_counter()
        if config.aggregation == AggregationLevel.BATCH:
            completed, failed = self._run_aggregated(run_id, records, config)
        else:
            completed, failed = self._run_single(run_id, records, config)
        duration_ms = (time.perf_counter() - start) * 1000

        # Finalize
        status = "completed" if failed == 0 else "completed_with_errors"
        self.store.finish_run(run_id, status, duration_ms)

        if self._run_logger:
            self._run_logger.log_event(
                "legal_summarization_end",
                "batch_runner",
                {
                    "run_id": run_id,
                    "completed": completed,
                    "failed": failed,
                    "duration_ms": duration_ms,
                },
                f"Run {run_id} finished: {completed} ok, {failed} failed in {duration_ms:.0f}ms",
            )

        # Write human-readable report
        report_path = self.store.write_report(run_id)
        logger.info("Run %s complete. Report: %s", run_id, report_path)

        return {
            "run_id": run_id,
            "status": status,
            "completed": completed,
            "failed": failed,
            "total": len(records),
            "duration_ms": duration_ms,
            "report_path": str(report_path),
        }

    # ------------------------------------------------------------------
    # Single-judgment iteration
    # ------------------------------------------------------------------

    def _run_single(
        self,
        run_id: str,
        records: list[JudgmentRecord],
        config: SummarizationConfig,
    ) -> tuple[int, int]:
        completed = 0
        failed = 0

        for i, rec in enumerate(records):
            logger.info(
                "[%d/%d] Summarizing record %d (%d chars)...",
                i + 1,
                len(records),
                rec.index,
                len(rec.input_text),
            )

            task_context = {
                "task_id": f"{run_id}_rec{rec.index}",
                "title": f"Legal judgment summary (record {rec.index})",
                "content": rec.input_text,
                "summarization_config": config,
                "required_capability": "legal_summarization",
            }

            t0 = time.perf_counter()
            try:
                result = self.agent.perform_task(task_context)
            except Exception as exc:
                logger.error("Record %d failed: %s", rec.index, exc)
                result = {"status": "failed", "summary": str(exc), "mode": "error"}
            inference_ms = (time.perf_counter() - t0) * 1000

            status = result.get("status", "failed")
            generated = result.get("summary", "")
            mode = result.get("mode", "unknown")

            self.store.store_result(
                run_id=run_id,
                record_index=rec.index,
                input_text=rec.input_text,
                reference_summary=rec.output_text,
                generated_summary=generated,
                mode=mode,
                status=status,
                inference_ms=inference_ms,
            )

            if status == "success":
                completed += 1
            else:
                failed += 1

            if self._run_logger:
                self._run_logger.log_task_execution(
                    task_id=f"{run_id}_rec{rec.index}",
                    agent_name=self.agent.name,
                    status=status,
                    duration_ms=inference_ms,
                    metadata={"mode": mode, "input_chars": len(rec.input_text)},
                )

        return completed, failed

    # ------------------------------------------------------------------
    # Aggregated (batch) summarization
    # ------------------------------------------------------------------

    def _run_aggregated(
        self,
        run_id: str,
        records: list[JudgmentRecord],
        config: SummarizationConfig,
    ) -> tuple[int, int]:
        """Send all judgment texts to the agent as a single batch prompt."""
        texts = [r.input_text for r in records]

        task_context = {
            "task_id": f"{run_id}_batch",
            "title": f"Aggregated legal summary ({len(records)} judgments)",
            "content": "",  # Not used in batch mode
            "judgments": texts,
            "summarization_config": config,
            "required_capability": "legal_summarization",
        }

        t0 = time.perf_counter()
        try:
            result = self.agent.perform_task(task_context)
        except Exception as exc:
            logger.error("Batch summarization failed: %s", exc)
            result = {"status": "failed", "summary": str(exc), "mode": "error"}
        inference_ms = (time.perf_counter() - t0) * 1000

        status = result.get("status", "failed")
        generated = result.get("summary", "")

        # Store as a single result with index -1 to mark it as batch
        self.store.store_result(
            run_id=run_id,
            record_index=-1,
            input_text=f"[{len(records)} judgments, {sum(len(t) for t in texts)} chars total]",
            reference_summary="",
            generated_summary=generated,
            mode=result.get("mode", "unknown"),
            status=status,
            inference_ms=inference_ms,
        )

        if status == "success":
            return (1, 0)
        return (0, 1)


if __name__ == "__main__":
    from summarization_config import SummarizationConfig

    logging.basicConfig(level=logging.INFO)
    runner = BatchRunner()
    # Use a small limit for quick check
    config = SummarizationConfig(limit=1)
    report = runner.run(config)
    print(f"Run completed with status: {report['status']}")
