#!/usr/bin/env python3
r"""CLI entry point for the legal-judgment summarization experiment.

Examples:

    # Verify the active Python and Hugging Face dependencies (no network call)
    .venv/bin/python -m src.Experiments.legal_summarization.main --check-dependencies

    # Inspect five streamed records from the default public Hub dataset
    .venv/bin/python -m src.Experiments.legal_summarization.main --describe --streaming

    # Evaluate 10 English judgments with the extractive baseline
    .venv/bin/python -m src.Experiments.legal_summarization.main \
        --mode extractive --limit 10

    # Summarize Urdu judgments for a general audience
    .venv/bin/python -m src.Experiments.legal_summarization.main \\
        --task-filter summary_ur --audience general_public --limit 20

    # Load a gated/private dataset using HF_TOKEN from .env (or prompt hidden)
    .venv/bin/python -m src.Experiments.legal_summarization.main \
        --dataset-id owner/private-dataset --prompt-for-hf-token --describe

    # Aggregated batch summary across 5 judgments
    .venv/bin/python -m src.Experiments.legal_summarization.main \\
        --config summary_en --aggregation batch --limit 5

    # List previous runs
    .venv/bin/python -m src.Experiments.legal_summarization.main --list-runs

    # Compare two runs side-by-side
    .venv/bin/python -m src.Experiments.legal_summarization.main \\
        --compare 20260327_120000 20260327_130000

    # Describe the dataset without running summarization
    .venv/bin/python -m src.Experiments.legal_summarization.main --describe
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure repo root is importable so ``src.*`` resolves when running this
# module directly (python src/Experiments/.../main.py) outside an installed
# package context.
_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _handoff_to_repo_runtime() -> None:
    """Re-launch a direct CLI invocation with the repository environment.

    IDE run configurations and bare ``python`` commands commonly select a
    system interpreter even after ``make install`` populated ``.venv``.  The
    experiment must use the locked repository runtime so compiled packages
    such as PyArrow and the Hugging Face stack are loaded as one compatible
    set.  Imports of this module are intentionally unaffected.
    """
    repo_environment = _repo_root / ".venv"
    try:
        active_environment = Path(sys.prefix).resolve()
        expected_environment = repo_environment.resolve()
    except OSError:
        return

    if active_environment == expected_environment:
        return

    executable_name = "python.exe" if os.name == "nt" else "python"
    repo_python = repo_environment / ("Scripts" if os.name == "nt" else "bin")
    repo_python /= executable_name
    if not repo_python.is_file():
        return

    command = [
        str(repo_python),
        "-m",
        "src.Experiments.legal_summarization.main",
        *sys.argv[1:],
    ]
    print(
        f"Re-launching legal evaluation with repository Python: {repo_python}",
        file=sys.stderr,
        flush=True,
    )
    try:
        os.execv(str(repo_python), command)
    except OSError as exc:
        raise SystemExit(
            f"Unable to launch the repository Python at {repo_python}: {exc}"
        ) from exc


if __name__ == "__main__":
    _handoff_to_repo_runtime()

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is optional for direct use
    pass
else:
    load_dotenv(_repo_root / ".env", override=False)

from src.Experiments.legal_summarization.batch_runner import \
    BatchRunner  # noqa: E402
from src.Experiments.legal_summarization.dataset_loader import (  # noqa: E402
    LegalDatasetLoader, huggingface_runtime_status)
from src.Experiments.legal_summarization.run_store import \
    RunStore  # noqa: E402
from src.Experiments.legal_summarization.summarization_config import (  # noqa: E402
    DEFAULT_LEGAL_SUMMARY_TOKENS, AggregationLevel, AudienceLevel,
    SummarizationConfig, SummarizationMode)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("legal_summarization.cli")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the module entry point.

    Returns:
        argparse.ArgumentParser: Resulting argparse.ArgumentParser value produced by the operation.
    """
    p = argparse.ArgumentParser(
        description="Legal Judgment Summarization — Artemis City Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- Run configuration ---
    run = p.add_argument_group("Summarization run")
    run.add_argument(
        "--config",
        "--task-filter",
        dest="task_filter",
        default="summary_en",
        help=(
            "Value required in the task column (default: summary_en). "
            "Pass an empty string to disable row filtering."
        ),
    )
    run.add_argument(
        "--split",
        default="train",
        help="Dataset split or slice expression (default: train)",
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
        default=DEFAULT_LEGAL_SUMMARY_TOKENS,
        help=f"Max summary tokens (default: {DEFAULT_LEGAL_SUMMARY_TOKENS})",
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

    # --- Dataset source ---
    dataset = p.add_argument_group("Dataset loading")
    dataset.add_argument(
        "--dataset-source",
        default="auto",
        choices=LegalDatasetLoader.SOURCES,
        help="auto tries local then Hub; local/hub force one source",
    )
    dataset.add_argument(
        "--dataset-path",
        default=None,
        help="Local Parquet file/directory (default: $LEGAL_DATASET_PATH)",
    )
    dataset.add_argument(
        "--dataset-id",
        default=None,
        help="Hugging Face dataset repository (default: $LEGAL_DATASET_ID or built-in legal corpus)",
    )
    dataset.add_argument(
        "--dataset-name",
        default=None,
        help="Optional named Hugging Face subset/configuration",
    )
    dataset.add_argument(
        "--revision",
        default=None,
        help="Hub branch, tag, or commit SHA (default: $LEGAL_DATASET_REVISION or main)",
    )
    dataset.add_argument(
        "--cache-dir",
        default=None,
        help="Hugging Face datasets cache directory",
    )
    dataset.add_argument(
        "--data-file",
        action="append",
        default=None,
        help="Repository data file/glob; repeat for multiple files",
    )
    dataset.add_argument(
        "--streaming",
        action="store_true",
        help="Stream Hub rows instead of downloading the complete dataset",
    )
    dataset.add_argument(
        "--prompt-for-hf-token",
        action="store_true",
        help="Request a missing Hugging Face token with hidden terminal input",
    )
    dataset.add_argument("--input-column", default="input")
    dataset.add_argument("--reference-column", default="output")
    dataset.add_argument("--instruction-column", default="instruction")
    dataset.add_argument("--task-column", default="task")

    # --- Inspection commands ---
    info = p.add_argument_group("Inspection")
    info.add_argument(
        "--check-dependencies",
        "--doctor",
        dest="check_dependencies",
        action="store_true",
        help=(
            "Print active Python, Hugging Face package, and token-source status "
            "without making a network request"
        ),
    )
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
    info.add_argument(
        "--grade-run",
        type=str,
        default=None,
        help="Run the automatic evaluation harness & reviewer on a past run ID and print feedback",
    )
    info.add_argument(
        "--eval-harness",
        "--auto-grade",
        dest="eval_harness",
        action="store_true",
        default=True,
        help="Run automatic multi-aspect rubric evaluation & review (default: enabled)",
    )

    return p


def main(argv: list[str] | None = None) -> None:
    """Run the primary workflow exposed by this module.

    Args:
        argv (list[str] | None): Argv value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    args = build_parser().parse_args(argv)

    if args.check_dependencies:
        status = huggingface_runtime_status()
        print(json.dumps(status, indent=2))
        if not status["ready"]:
            raise SystemExit(1)
        return

    loader = LegalDatasetLoader(
        local_path=args.dataset_path,
        source=args.dataset_source,
        dataset_id=args.dataset_id,
        dataset_name=args.dataset_name,
        revision=args.revision,
        cache_dir=args.cache_dir,
        data_files=args.data_file,
        streaming=args.streaming,
        prompt_for_token=args.prompt_for_hf_token,
        input_column=args.input_column,
        reference_column=args.reference_column,
        instruction_column=args.instruction_column,
        task_column=args.task_column,
    )
    store = RunStore()

    # --- Inspection commands (no summarization) ---

    if args.describe:
        info = loader.describe(config=args.task_filter or None, split=args.split)
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

    if args.grade_run:
        run = store.get_run(args.grade_run)
        if not run:
            print(f"Run '{args.grade_run}' not found.")
            return
        results = store.get_results(args.grade_run)
        if not results:
            print(f"No results found for run '{args.grade_run}'.")
            return

        from src.Experiments.legal_summarization.eval_harness import \
            LegalEvalHarness

        harness = LegalEvalHarness()
        eval_reports = []
        for r in results:
            eval_res = harness.evaluate_record(
                generated_summary=r.get("generated_summary", ""),
                source_text=r.get("input_preview", ""),
                reference_summary=r.get("reference_summary"),
            )
            eval_reports.append(
                {
                    "record_index": r["record_index"],
                    "score": eval_res.overall_score,
                    "grade": eval_res.grade,
                    "verdict": eval_res.review["verdict"],
                    "strengths": eval_res.review["strengths"],
                    "weaknesses": eval_res.review["weaknesses"],
                    "recommendations": eval_res.review["recommendations"],
                }
            )

        print(f"=== Automatic Evaluation & Review for Run: {args.grade_run} ===")
        print(json.dumps(eval_reports, indent=2))
        return

    # --- Summarization run ---

    # Optionally wire in the core RunLogger for event integration
    run_logger = None
    try:
        from src.utils.run_logger import init_run_logger

        run_logger = init_run_logger()
    except Exception:
        logger.info(
            "Core RunLogger not available — proceeding without event integration."
        )

    config = SummarizationConfig(
        dataset_config=args.task_filter,
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
    try:
        result = runner.run(config)
    except Exception as exc:
        logger.error("Evaluation failed: %s", exc)
        if run_logger:
            run_logger.finalize_run(
                status="failed",
                summary={"legal_summarization_error": str(exc)},
            )
        raise SystemExit(f"Evaluation failed: {exc}") from exc

    print(f"\n{'=' * 60}")
    print(f"Run ID:     {result['run_id']}")
    print(f"Status:     {result['status']}")
    print(f"Failed:     {result['failed']}")
    print(f"Duration:   {result['duration_ms']:.0f} ms")
    print(f"Report:     {result.get('report_path', 'N/A')}")
    if result.get("metrics"):
        print("Metrics:")
        for name, value in sorted(result["metrics"].items()):
            print(f"  {name:<22} {value:.4f}")
    print(f"{'=' * 60}")

    if run_logger:
        run_logger.finalize_run(
            status=result["status"],
            summary={"legal_summarization_run_id": result["run_id"]},
        )


if __name__ == "__main__":
    main()
