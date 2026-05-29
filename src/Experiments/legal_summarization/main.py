#!/usr/bin/env python3
"""CLI entry point for the legal-judgment summarization experiment.

Examples:

    # Summarize 10 English judgments with default settings
    python -m Projects.Codex_Experiments.legal_summarization.main --limit 10

    # Summarize Urdu judgments for a general audience
    python -m Projects.Codex_Experiments.legal_summarization.main \\
        --config summary_ur --audience general_public --limit 20

    # Aggregated batch summary across 5 judgments
    python -m Projects.Codex_Experiments.legal_summarization.main \\
        --config summary_en --aggregation batch --limit 5

    # List previous runs
    python -m Projects.Codex_Experiments.legal_summarization.main --list-runs

    # Compare two runs side-by-side
    python -m Projects.Codex_Experiments.legal_summarization.main \\
        --compare 20260327_120000 20260327_130000

    # Describe the dataset without running summarization
    python -m Projects.Codex_Experiments.legal_summarization.main --describe
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from sys import path

# Ensure repo root is importable
_repo_root = Path(__file__).resolve().parents[3]
path.insert(0, str(_repo_root))

from Projects.Codex_Experiments.legal_summarization.batch_runner import (
    BatchRunner,  # noqa: E402
)
from Projects.Codex_Experiments.legal_summarization.dataset_loader import (  # noqa: E402
    LegalDatasetLoader,
)
from Projects.Codex_Experiments.legal_summarization.run_store import (
    RunStore,  # noqa: E402
)
from Projects.Codex_Experiments.legal_summarization.summarization_config import (  # noqa: E402
    AggregationLevel,
    AudienceLevel,
    SummarizationConfig,
    SummarizationMode,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("legal_summarization.cli")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Legal Judgment Summarization — Codex Experiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- Run configuration ---
    run = p.add_argument_group("Summarization run")
    run.add_argument(
        "--config",
        default="summary_en",
        choices=LegalDatasetLoader.SUMMARIZATION_CONFIGS,
        help="Dataset config subset (default: summary_en)",
    )
    run.add_argument(
        "--split",
        default="train",
        choices=["train", "validation", "test"],
        help="Dataset split (default: train)",
    )
    run.add_argument("--limit", type=int, default=None, help="Max records to process")
    run.add_argument(
        "--mode",
        default="abstractive",
        choices=["abstractive", "extractive"],
        help="Summarization mode (default: abstractive)",
    )
    run.add_argument(
        "--aggregation",
        default="single",
        choices=["single", "batch"],
        help="single = per-judgment, batch = aggregated (default: single)",
    )
    run.add_argument(
        "--audience",
        default="legal_professional",
        choices=["legal_professional", "general_public", "academic"],
        help="Target audience (default: legal_professional)",
    )
    run.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Max summary tokens (default: 512)",
    )
    run.add_argument(
        "--temperature",
        type=float,
        default=0.4,
        help="LLM sampling temperature (default: 0.4)",
    )
    run.add_argument(
        "--custom-prompt",
        type=str,
        default=None,
        help="Additional user-prompt text appended to every request",
    )
    run.add_argument("--tag", default="", help="Free-form tag for this run")

    # --- Dataset path ---
    p.add_argument(
        "--dataset-path",
        default=None,
        help="Override local dataset path (default: $LEGAL_DATASET_PATH or Exo_Homelab location)",
    )

    # --- Inspection commands ---
    info = p.add_argument_group("Inspection")
    info.add_argument(
        "--describe",
        action="store_true",
        help="Print dataset metadata and exit",
    )
    info.add_argument(
        "--list-runs",
        action="store_true",
        help="List recent summarization runs and exit",
    )
    info.add_argument(
        "--show-run",
        type=str,
        default=None,
        help="Show details + sample results for a run ID",
    )
    info.add_argument(
        "--compare",
        nargs="+",
        metavar="RUN_ID",
        help="Compare two or more runs side-by-side",
    )

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    loader = LegalDatasetLoader(local_path=args.dataset_path)
    store = RunStore()

    # --- Inspection commands (no summarization) ---

    if args.describe:
        info = loader.describe(config=args.config, split=args.split)
        print(json.dumps(info, indent=2))
        return

    if args.list_runs:
        runs = store.list_runs()
        if not runs:
            print("No runs recorded yet.")
            return
        print(f"{'Run ID':<20} {'Status':<22} {'Records':>8} {'Duration':>10}")
        print("-" * 64)
        for r in runs:
            dur = f"{r.get('duration_ms', 0):.0f}ms"
            total = r.get("total_records", "?")
            print(f"{r['run_id']:<20} {r['status']:<22} {total:>8} {dur:>10}")
        return

    if args.show_run:
        run = store.get_run(args.show_run)
        if not run:
            print(f"Run '{args.show_run}' not found.")
            return
        print(json.dumps(run, indent=2))
        results = store.get_results(args.show_run, limit=5)
        if results:
            print(f"\nFirst {len(results)} results:")
            for r in results:
                print(
                    f"  [{r['record_index']}] {r['status']} — {r['generated_summary'][:120]}..."
                )
        return

    if args.compare:
        runs = store.compare_runs(args.compare)
        if not runs:
            print("No matching runs found.")
            return
        for r in runs:
            print(f"\n--- {r['run_id']} ---")
            print(json.dumps(r, indent=2))
        return

    # --- Summarization run ---

    # Optionally wire in the core RunLogger for event integration
    run_logger = None
    try:
        from utils.run_logger import init_run_logger

        run_logger = init_run_logger(
            log_dir="logs",
            db_path="data/run_logs.db",
        )
    except Exception:
        logger.info(
            "Core RunLogger not available — proceeding without event integration."
        )

    config = SummarizationConfig(
        dataset_config=args.config,
        mode=SummarizationMode(args.mode),
        aggregation=AggregationLevel(args.aggregation),
        audience=AudienceLevel(args.audience),
        max_summary_tokens=args.max_tokens,
        temperature=args.temperature,
        custom_user_prompt=args.custom_prompt,
        split=args.split,
        limit=args.limit,
        batch_tag=args.tag,
    )

    runner = BatchRunner(loader=loader, store=store, run_logger=run_logger)
    result = runner.run(config)

    print(f"\n{'=' * 60}")
    print(f"Run ID:     {result['run_id']}")
    print(f"Status:     {result['status']}")
    print(f"Failed:     {result['failed']}")
    print(f"Duration:   {result['duration_ms']:.0f} ms")
    print(f"Report:     {result.get('report_path', 'N/A')}")
    print(f"{'=' * 60}")

    if run_logger:
        run_logger.finalize_run(
            status=result["status"],
            summary={"legal_summarization_run_id": result["run_id"]},
        )


if __name__ != "__main__":
    pass
else:
    main()
