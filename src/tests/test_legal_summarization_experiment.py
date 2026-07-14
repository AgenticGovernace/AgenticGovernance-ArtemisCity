import json
import sqlite3
import sys
import types

import pytest

from src.Experiments.legal_summarization.batch_runner import BatchRunner
from src.Experiments.legal_summarization.dataset_loader import (
    JudgmentRecord,
    LegalDatasetLoader,
    resolve_hf_token,
)
from src.Experiments.legal_summarization.evaluation import (
    aggregate_metrics,
    evaluate_summary,
)
from src.Experiments.legal_summarization.legal_summarizer_agent import (
    LegalSummarizerAgent,
)
from src.Experiments.legal_summarization.main import build_parser
from src.Experiments.legal_summarization.run_store import RunStore
from src.Experiments.legal_summarization.summarization_config import (
    SummarizationConfig,
    SummarizationMode,
)


def test_resolve_hf_token_prefers_official_environment(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "official-token")
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "legacy-token")

    token, source = resolve_hf_token()

    assert token == "official-token"
    assert source == "HF_TOKEN"


def test_resolve_hf_token_can_prompt_without_persisting(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)

    token, source = resolve_hf_token(
        prompt=True,
        prompt_fn=lambda _message: "runtime-token",
    )

    assert token == "runtime-token"
    assert source == "prompt"
    assert "HF_TOKEN" not in __import__("os").environ


def test_huggingface_loader_passes_current_options_and_maps_columns(
    monkeypatch,
):
    captured = {}

    def fake_load_dataset(**kwargs):
        captured.update(kwargs)
        return [
            {
                "prompt": "skip",
                "document": "ignored",
                "gold": "ignored",
                "kind": "other",
            },
            {
                "prompt": "summarize",
                "document": "Source text",
                "gold": "Reference text",
                "kind": "summary",
            },
        ]

    fake_datasets = types.ModuleType("datasets")
    fake_datasets.load_dataset = fake_load_dataset
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    monkeypatch.setenv("HF_TOKEN", "secret-token")

    loader = LegalDatasetLoader(
        source="hub",
        dataset_id="owner/corpus",
        dataset_name="named",
        revision="abc123",
        cache_dir="/tmp/hf-cache",
        data_files=["data/*.parquet"],
        streaming=True,
        input_column="document",
        reference_column="gold",
        instruction_column="prompt",
        task_column="kind",
    )
    records = loader.load(config="summary", split="test", limit=1)

    assert captured == {
        "path": "owner/corpus",
        "name": "named",
        "split": "test",
        "revision": "abc123",
        "token": "secret-token",
        "streaming": True,
        "cache_dir": "/tmp/hf-cache",
        "data_files": ["data/*.parquet"],
    }
    assert records == [
        JudgmentRecord(
            index=0,
            instruction="summarize",
            input_text="Source text",
            output_text="Reference text",
            task="summary",
            config="summary",
            split="test",
        )
    ]
    assert loader.last_load_info["token_source"] == "HF_TOKEN"
    assert loader.last_load_info["authenticated"] is True
    assert "secret-token" not in json.dumps(loader.last_load_info)


def test_huggingface_loader_requires_task_column_only_when_filtering(monkeypatch):
    fake_datasets = types.ModuleType("datasets")
    fake_datasets.load_dataset = lambda **_kwargs: [
        {"document": "Source", "summary": "Reference"}
    ]
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)

    loader = LegalDatasetLoader(
        source="hub",
        input_column="document",
        reference_column="summary",
    )

    records = loader.load(config=None, limit=1)
    assert records[0].input_text == "Source"

    with pytest.raises(ValueError, match="Task filter"):
        loader.load(config="summary", limit=1)


def test_reference_metrics_and_aggregation_are_deterministic():
    metrics = evaluate_summary(
        "Court allowed appeal",
        "Court allowed appeal",
        "The Court allowed the appeal after review",
    )

    assert metrics["rouge1_f1"] == pytest.approx(1.0)
    assert metrics["rouge_l_f1"] == pytest.approx(1.0)
    aggregate = aggregate_metrics([metrics, metrics])
    assert aggregate == pytest.approx(metrics)


def test_legal_agent_uses_current_extractive_baseline_without_exo():
    agent = LegalSummarizerAgent()
    config = SummarizationConfig(
        mode=SummarizationMode.EXTRACTIVE,
        max_summary_tokens=5,
    )

    result = agent.perform_task(
        {
            "content": "First legal sentence has details. Second sentence is later.",
            "summarization_config": config,
        }
    )

    assert result["status"] == "success"
    assert result["provider"] == "extractive_baseline"
    assert len(result["summary"].split()) == 5


def test_run_store_migrates_and_persists_evaluation_metrics(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                finished_at TEXT, status TEXT NOT NULL DEFAULT 'running',
                config_json TEXT NOT NULL, dataset_config TEXT, split TEXT,
                total_records INTEGER DEFAULT 0, completed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0, duration_ms REAL
            );
            CREATE TABLE results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, record_index INTEGER NOT NULL,
                input_preview TEXT, reference_summary TEXT,
                generated_summary TEXT, mode TEXT, status TEXT NOT NULL,
                inference_ms REAL, input_chars INTEGER, output_chars INTEGER,
                created_at REAL NOT NULL
            );
            """
        )

    store = RunStore(db_path=str(db_path), report_dir=str(tmp_path / "reports"))
    store.start_run(
        "run-1",
        "{}",
        "summary_en",
        "test",
        1,
        dataset_info={
            "dataset_id": "owner/corpus",
            "revision": "abc123",
            "source": "hub",
        },
    )
    store.store_result(
        "run-1",
        0,
        "source",
        "reference",
        "generated",
        "extractive",
        "success",
        2.0,
        metrics={"rouge1_f1": 0.5},
    )
    store.finish_run("run-1", "completed", 2.0, metrics={"rouge1_f1": 0.5})

    run = store.get_run("run-1")
    result = store.get_results("run-1")[0]
    assert run["dataset_id"] == "owner/corpus"
    assert json.loads(run["metrics_json"])["rouge1_f1"] == pytest.approx(0.5)
    assert json.loads(result["metrics_json"])["rouge1_f1"] == pytest.approx(0.5)
    assert "ROUGE-1 F1" in store.write_report("run-1").read_text()


def test_batch_runner_persists_aggregate_reference_metrics(tmp_path):
    records = [
        JudgmentRecord(0, "", "alpha beta", "alpha beta", "summary", "summary", "test"),
        JudgmentRecord(
            1, "", "gamma delta", "gamma delta", "summary", "summary", "test"
        ),
    ]

    class FakeLoader:
        last_load_info = {
            "source": "fixture",
            "dataset_id": "test/corpus",
            "revision": "test",
        }

        def load(self, **_kwargs):
            return records

    class FakeAgent:
        name = "Fake Legal Agent"

        def perform_task(self, task_context):
            return {
                "status": "success",
                "summary": task_context["content"],
                "mode": "fixture",
            }

    store = RunStore(
        db_path=str(tmp_path / "runs.db"),
        report_dir=str(tmp_path / "reports"),
    )
    result = BatchRunner(
        loader=FakeLoader(),
        agent=FakeAgent(),
        store=store,
    ).run(SummarizationConfig(dataset_config="summary", split="test", limit=2))

    assert result["status"] == "completed"
    assert result["metrics"]["rouge1_f1"] == pytest.approx(1.0)
    stored = store.get_run(result["run_id"])
    assert json.loads(stored["metrics_json"])["rouge_l_f1"] == pytest.approx(1.0)


def test_cli_exposes_generic_huggingface_options():
    args = build_parser().parse_args(
        [
            "--dataset-id",
            "owner/corpus",
            "--dataset-name",
            "named",
            "--task-filter",
            "",
            "--streaming",
            "--prompt-for-hf-token",
        ]
    )

    assert args.dataset_id == "owner/corpus"
    assert args.dataset_name == "named"
    assert args.task_filter == ""
    assert args.streaming is True
    assert args.prompt_for_hf_token is True
