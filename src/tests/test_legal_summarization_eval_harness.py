"""Tests for the legal summarization automatic evaluation harness & review engine."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.Experiments.legal_summarization.batch_runner import BatchRunner
from src.Experiments.legal_summarization.dataset_loader import JudgmentRecord
from src.Experiments.legal_summarization.eval_harness import (
    EvalResult,
    LegalEvalHarness,
)
from src.Experiments.legal_summarization.evaluation import evaluate_summary_with_review
from src.Experiments.legal_summarization.main import build_parser, main
from src.Experiments.legal_summarization.run_store import RunStore
from src.Experiments.legal_summarization.summarization_config import (
    AudienceLevel,
    SummarizationConfig,
)


def test_eval_harness_computes_multi_aspect_scores_and_grade():
    harness = LegalEvalHarness(pass_threshold=70.0)

    source = (
        "The appellant filed an appeal against the conviction under Section 302 of the Pakistan Penal Code. "
        "The primary legal issue was whether the prosecution proved guilt beyond reasonable doubt. "
        "The Supreme Court held that circumstantial evidence was insufficient to sustain the conviction. "
        "Accordingly, the appeal was allowed and the accused was acquitted."
    )

    summary = (
        "In this criminal appeal regarding a conviction under Section 302, the main issue was the sufficiency of circumstantial evidence. "
        "The court held that the evidence was inadequate and allowed the appeal, acquitting the appellant."
    )

    reference = "The Supreme Court allowed the appeal and acquitted the appellant convicted under Section 302 due to insufficient evidence."

    config = SummarizationConfig(audience=AudienceLevel.LEGAL_PROFESSIONAL)
    result = harness.evaluate_record(
        generated_summary=summary,
        source_text=source,
        reference_summary=reference,
        config=config,
    )

    assert isinstance(result, EvalResult)
    assert result.overall_score >= 70.0
    assert result.passed is True
    assert result.grade in {"A+", "A", "B"}
    assert "legal_structure" in result.criterion_scores
    assert "faithfulness" in result.criterion_scores
    assert "conciseness" in result.criterion_scores
    assert "audience_suitability" in result.criterion_scores
    assert "reference_alignment" in result.criterion_scores

    review = result.review
    assert review["verdict"] == "PASS"
    assert len(review["strengths"]) > 0


def test_eval_harness_detects_missing_legal_elements_and_unverified_citations():
    harness = LegalEvalHarness(pass_threshold=75.0)

    source = "The tenant requested a rent freeze under Section 12. The tribunal agreed."
    summary = (
        "The court cited Section 999 and Art. 404 in 2099 and dismissed the claim."
    )

    result = harness.evaluate_record(
        generated_summary=summary,
        source_text=source,
    )

    assert result.criterion_scores["faithfulness"] < 100.0
    assert len(result.review["weaknesses"]) > 0
    assert any(
        "citations" in w.lower() or "unverified" in w.lower()
        for w in result.review["weaknesses"]
    )


def test_evaluate_summary_with_review_convenience_function():
    out = evaluate_summary_with_review(
        generated="The Court held that the claim has merit and allowed the appeal.",
        source="The Court held that the claim has merit and allowed the appeal.",
    )

    assert "overall_score" in out
    assert "grade" in out
    assert "review" in out


def test_run_store_persists_and_reports_eval_grades(tmp_path):
    store = RunStore(
        db_path=str(tmp_path / "runs.db"),
        report_dir=str(tmp_path / "reports"),
    )

    store.start_run("eval-run-1", "{}", "summary_en", "test", 1)
    eval_payload = {
        "overall_score": 92.0,
        "grade": "A",
        "review": {
            "verdict": "PASS",
            "strengths": ["Accurate holding"],
            "weaknesses": [],
            "recommendations": [],
        },
    }

    store.store_result(
        run_id="eval-run-1",
        record_index=0,
        input_text="Full legal judgement source text here.",
        reference_summary="Reference summary.",
        generated_summary="The Court held in favor of petitioner and allowed the appeal.",
        mode="extractive",
        status="success",
        inference_ms=10.0,
        metrics={"rouge1_f1": 0.85},
        eval_result=eval_payload,
    )
    store.finish_run("eval-run-1", "completed", 10.0)

    report_path = store.write_report("eval-run-1")
    report_text = report_path.read_text()

    assert "Results & Grade Summary" in report_text
    assert "Automatic Grade:** A (92.0/100)" in report_text
    assert "Verdict:** PASS" in report_text


def test_batch_runner_automatically_evaluates_and_grades_records(tmp_path):
    records = [
        JudgmentRecord(
            index=0,
            instruction="summarize",
            input_text="The appellant appealed conviction under Section 302. The court held evidence was weak and allowed appeal.",
            output_text="Court allowed appeal under Section 302 due to weak evidence.",
            task="summary_en",
            config="summary_en",
            split="test",
        )
    ]

    class FakeLoader:
        last_load_info = {"source": "fixture", "dataset_id": "test/legal"}

        def load(self, **_kwargs):
            return records

    class FakeAgent:
        name = "Fake Agent"

        def perform_task(self, task_context):
            return {
                "status": "success",
                "summary": "The court held evidence was weak and allowed appeal under Section 302.",
                "mode": "extractive",
            }

    store = RunStore(
        db_path=str(tmp_path / "batch.db"),
        report_dir=str(tmp_path / "reports"),
    )
    runner = BatchRunner(loader=FakeLoader(), agent=FakeAgent(), store=store)
    result = runner.run(SummarizationConfig(limit=1))

    assert result["status"] == "completed"
    results = store.get_results(result["run_id"])
    assert len(results) == 1
    assert results[0]["eval_grade"] in {"A+", "A", "B", "C"}
    assert results[0]["eval_score"] > 0


def test_cli_grade_run_command(tmp_path, capsys):
    db_path = tmp_path / "cli.db"
    store = RunStore(db_path=str(db_path), report_dir=str(tmp_path / "reports"))

    store.start_run("cli-run-100", "{}", "summary_en", "test", 1)
    store.store_result(
        run_id="cli-run-100",
        record_index=0,
        input_text="The court allowed the appeal.",
        reference_summary="Court allowed appeal.",
        generated_summary="The court allowed the appeal.",
        mode="extractive",
        status="success",
        inference_ms=5.0,
    )
    store.finish_run("cli-run-100", "completed", 5.0)

    # Inject DB path via env or monkeypatch
    import os

    os.environ["ARTEMIS_LEGAL_SUMMARIZATION_DB"] = str(db_path)

    try:
        main(["--grade-run", "cli-run-100"])
        captured = capsys.readouterr().out
        assert "Automatic Evaluation & Review for Run: cli-run-100" in captured
        assert "score" in captured
        assert "grade" in captured
    finally:
        os.environ.pop("ARTEMIS_LEGAL_SUMMARIZATION_DB", None)
