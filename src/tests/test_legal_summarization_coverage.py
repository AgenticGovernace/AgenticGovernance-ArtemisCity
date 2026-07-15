"""Additional branch coverage for the legal-summarization evaluation surface."""

from __future__ import annotations

import builtins
import json
import runpy
import sqlite3
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.Experiments.legal_summarization.batch_runner as batch_runner_module
import src.Experiments.legal_summarization.dataset_loader as dataset_loader_module
from src.Experiments.legal_summarization import main as cli
from src.Experiments.legal_summarization.batch_runner import BatchRunner
from src.Experiments.legal_summarization.dataset_loader import (
    JudgmentRecord,
    LegalDatasetLoader,
    huggingface_runtime_status,
    resolve_hf_token,
)
from src.Experiments.legal_summarization.evaluation import evaluate_summary
from src.Experiments.legal_summarization.legal_summarizer_agent import (
    LegalSummarizerAgent,
)
from src.Experiments.legal_summarization.run_store import RunStore
from src.Experiments.legal_summarization.summarization_config import (
    AggregationLevel,
    AudienceLevel,
    SummarizationConfig,
)


def test_cli_direct_file_bootstrap_adds_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct script execution restores the repo root needed by ``src`` imports."""
    repo_root = str(cli.Path(cli.__file__).resolve().parents[3])
    isolated_path = [entry for entry in sys.path if entry != repo_root]
    monkeypatch.setattr(sys, "path", isolated_path)

    namespace = runpy.run_path(cli.__file__, run_name="legal_cli_bootstrap_test")

    assert str(namespace["_repo_root"]) == repo_root
    assert isolated_path[0] == repo_root


def test_cli_hands_bare_python_invocation_to_repo_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_root = tmp_path / "repo"
    binary_dir = "Scripts" if cli.os.name == "nt" else "bin"
    executable = "python.exe" if cli.os.name == "nt" else "python"
    repo_python = repo_root / ".venv" / binary_dir / executable
    repo_python.parent.mkdir(parents=True)
    repo_python.touch()
    execv = MagicMock()

    monkeypatch.setattr(cli, "_repo_root", repo_root)
    monkeypatch.setattr(cli.sys, "prefix", str(tmp_path / "system-python"))
    monkeypatch.setattr(cli.sys, "argv", ["main.py", "--doctor"])
    monkeypatch.setattr(cli.os, "execv", execv)

    cli._handoff_to_repo_runtime()

    execv.assert_called_once_with(
        str(repo_python),
        [
            str(repo_python),
            "-m",
            "src.Experiments.legal_summarization.main",
            "--doctor",
        ],
    )


def test_cli_does_not_relaunch_inside_repo_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_root = tmp_path / "repo"
    binary_dir = "Scripts" if cli.os.name == "nt" else "bin"
    executable = "python.exe" if cli.os.name == "nt" else "python"
    repo_python = repo_root / ".venv" / binary_dir / executable
    repo_python.parent.mkdir(parents=True)
    repo_python.touch()
    execv = MagicMock()

    monkeypatch.setattr(cli, "_repo_root", repo_root)
    monkeypatch.setattr(cli.sys, "prefix", str(repo_root / ".venv"))
    monkeypatch.setattr(cli.os, "execv", execv)

    cli._handoff_to_repo_runtime()

    execv.assert_not_called()


def _record(index: int = 0, *, reference: str = "reference") -> JudgmentRecord:
    return JudgmentRecord(
        index=index,
        instruction="summarize",
        input_text=f"source {index}",
        output_text=reference,
        task="summary_en",
        config="summary_en",
        split="test",
    )


def test_dataset_cache_defaults_to_canonical_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("HF_DATASETS_CACHE", raising=False)

    loader = LegalDatasetLoader(source="hub")

    assert loader.cache_dir == str(tmp_path / "data" / "huggingface")


def test_token_resolution_covers_explicit_legacy_none_and_empty_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACE_API_KEY", " legacy ")
    assert resolve_hf_token(" explicit ") == ("explicit", "explicit")
    assert resolve_hf_token() == ("legacy", "HUGGINGFACE_API_KEY")

    monkeypatch.delenv("HUGGINGFACE_API_KEY")
    assert resolve_hf_token() == (None, "none")
    with pytest.raises(RuntimeError, match="No Hugging Face token"):
        resolve_hf_token(prompt=True, prompt_fn=lambda _message: "   ")


def test_token_prompt_requires_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.setattr(
        "src.Experiments.legal_summarization.dataset_loader.sys.stdin",
        SimpleNamespace(isatty=lambda: False),
    )

    with pytest.raises(RuntimeError, match="interactive terminal"):
        resolve_hf_token(prompt=True)


def test_token_prompt_uses_hidden_input_when_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.setattr(
        "src.Experiments.legal_summarization.dataset_loader.sys.stdin",
        SimpleNamespace(isatty=lambda: True),
    )
    monkeypatch.setattr(
        "src.Experiments.legal_summarization.dataset_loader.getpass.getpass",
        lambda _message: "interactive-token",
    )

    assert resolve_hf_token(prompt=True) == ("interactive-token", "prompt")


def test_loader_validates_source_and_limit() -> None:
    with pytest.raises(ValueError, match="source must be one of"):
        LegalDatasetLoader(source="ftp")

    with pytest.raises(ValueError, match="limit must be at least 1"):
        LegalDatasetLoader(source="local").load(limit=0)
    assert LegalDatasetLoader(source="local").load(limit=1) == []


def test_loader_discovers_local_configs_and_ignores_unusable_files(tmp_path) -> None:
    (tmp_path / "summary_en").mkdir()
    (tmp_path / "repair").mkdir()
    (tmp_path / "unlisted").mkdir()
    (tmp_path / "tiny.parquet").write_bytes(b"tiny")
    (tmp_path / "notes.txt").write_text("not parquet")

    loader = LegalDatasetLoader(local_path=str(tmp_path), source="local")

    assert loader.available_configs() == ["repair", "summary_en"]
    assert loader.load(config=None) == []
    assert loader.last_load_info["source"] == "local"
    assert loader.last_load_info["record_count"] == 0

    file_loader = LegalDatasetLoader(
        local_path=str(tmp_path / "notes.txt"), source="local"
    )
    assert file_loader.available_configs() == []
    assert file_loader.load(config=None) == []


def test_loader_reads_local_parquet_rows_with_column_mapping(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet = tmp_path / "summary_en" / "test-000.parquet"
    parquet.parent.mkdir()
    parquet.write_bytes(b"x" * 2048)
    rows = [
        {"input": "skip", "output": "skip", "task": "other", "instruction": ""},
        {
            "input": "source",
            "output": "reference",
            "task": "summary_en",
            "instruction": "summarize",
        },
    ]

    class Cell:
        def __init__(self, value):
            self.value = value

        def as_py(self):
            return self.value

    class Table:
        column_names = list(rows[0])
        num_rows = len(rows)

        @staticmethod
        def column(name):
            return [Cell(row[name]) for row in rows]

    parquet_module = types.ModuleType("pyarrow.parquet")
    parquet_module.read_table = lambda _path: Table()
    pyarrow_module = types.ModuleType("pyarrow")
    pyarrow_module.parquet = parquet_module
    monkeypatch.setitem(sys.modules, "pyarrow", pyarrow_module)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", parquet_module)

    loader = LegalDatasetLoader(local_path=str(tmp_path), source="auto")
    records = loader.load(config="summary_en", split="test", limit=1)

    assert records == [
        JudgmentRecord(
            0,
            "summarize",
            "source",
            "reference",
            "summary_en",
            "summary_en",
            "test",
        )
    ]
    assert loader.last_load_info["source"] == "local"


def test_loader_handles_missing_pyarrow(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet = tmp_path / "data.parquet"
    parquet.write_bytes(b"x" * 2048)
    real_import = builtins.__import__

    def reject_pyarrow(name, *args, **kwargs):
        if name == "pyarrow.parquet":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_pyarrow)

    assert LegalDatasetLoader(local_path=str(parquet), source="local").load() == []


def test_loader_describe_and_row_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = LegalDatasetLoader(source="hub")
    monkeypatch.setattr(loader, "load", lambda *_args, **_kwargs: [_record()])
    loader.last_load_info = {"source": "fixture", "record_count": 1}

    description = loader.describe("summary_en", "test")

    assert description["sample_count"] == 1
    assert description["sample_input_length"] == len("source 0")
    assert description["sample_reference_length"] == len("reference")
    with pytest.raises(ValueError, match="Input column 'input'"):
        loader._record_from_row({"task": "summary_en"}, 0, "summary_en", "test")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (RuntimeError("401 gated token"), "authentication failed"),
        (RuntimeError("network offline"), "Unable to load Hugging Face dataset"),
    ],
)
def test_hub_loader_translates_dataset_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    datasets_module = types.ModuleType("datasets")

    def fail(**_kwargs):
        raise error

    datasets_module.load_dataset = fail
    monkeypatch.setitem(sys.modules, "datasets", datasets_module)

    with pytest.raises(RuntimeError, match=message):
        LegalDatasetLoader(source="hub").load(limit=1)


@pytest.mark.parametrize("dependency", ["datasets", "pyarrow"])
def test_hub_loader_reports_exact_dependency_and_interpreter(
    monkeypatch: pytest.MonkeyPatch, dependency: str
) -> None:
    real_import_module = dataset_loader_module.importlib.import_module

    def reject_dependency(name, package=None):
        if name == dependency:
            raise ModuleNotFoundError(
                f"No module named '{dependency}'", name=dependency
            )
        return real_import_module(name, package)

    monkeypatch.delitem(sys.modules, dependency, raising=False)
    monkeypatch.setattr(
        dataset_loader_module.importlib,
        "import_module",
        reject_dependency,
    )

    with pytest.raises(RuntimeError, match="Hugging Face runtime check") as exc_info:
        LegalDatasetLoader(source="hub").load(limit=1)

    message = str(exc_info.value)
    assert dependency in message
    assert sys.executable in message
    assert "make legal-summarization" in message


def test_huggingface_runtime_status_is_actionable_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_do_not_emit_this_value")

    status = huggingface_runtime_status()
    serialized = json.dumps(status)

    assert status["ready"] is True
    assert status["python"]["executable"] == sys.executable
    assert status["python"]["required"] == ">=3.12,<3.13"
    assert status["environment_file"]["token_source"] == "HF_TOKEN"
    assert "hf_do_not_emit_this_value" not in serialized


def test_summarization_config_prompts_and_round_trip() -> None:
    config = SummarizationConfig(
        audience=AudienceLevel.GENERAL_PUBLIC,
        custom_user_prompt="Use bullets.",
        max_summary_tokens=42,
    )

    assert "general audience" in config.system_prompt
    assert "Use bullets." in config.build_user_prompt("judgment")
    batch = config.build_batch_prompt(["one", "two"])
    assert "2 legal judgments" in batch
    assert "[Judgment 2]\ntwo" in batch
    restored = SummarizationConfig.from_dict(json.loads(config.to_json()))
    assert restored.to_dict() == config.to_dict()

    override = SummarizationConfig(system_prompt_override="custom system")
    assert override.system_prompt == "custom system"
    override.audience = "unknown"  # type: ignore[assignment]
    assert (
        "expert legal analyst"
        in override._SYSTEM_PROMPTS[AudienceLevel.LEGAL_PROFESSIONAL]
    )
    assert evaluate_summary("one", "one two", "one two three")["rouge_l_f1"] > 0


def test_legal_agent_delegates_governance_and_abstractive_execution() -> None:
    llm = MagicMock()
    llm.get_sandbox_policies.return_value = ["policy"]
    llm.get_sandbox_actions.return_value = [{"tool": "network"}]
    llm.perform_task.return_value = {"status": "success", "summary": "generated"}
    agent = LegalSummarizerAgent(llm_agent=llm)

    assert agent.get_sandbox_policies() == ["policy"]
    assert (
        agent.get_sandbox_actions({"summarization_config": {"mode": "extractive"}})
        == []
    )
    assert agent.get_sandbox_actions({}) == [{"tool": "network"}]
    result = agent.perform_task(
        {
            "task_id": "batch",
            "judgments": [" one ", "", "two"],
            "summarization_config": SummarizationConfig(
                aggregation=AggregationLevel.BATCH
            ),
        }
    )
    assert result["summary"] == "generated"
    assert result["mode"] == "abstractive"
    request = llm.perform_task.call_args.args[0]
    assert "[Judgment 1]\none" in request["prompt"]
    assert request["system_prompt"]


def test_legal_agent_handles_empty_and_zero_length_extractive_input() -> None:
    agent = LegalSummarizerAgent(llm_agent=MagicMock())
    failed = agent.perform_task(
        {"content": " ", "summarization_config": {"mode": "extractive"}}
    )
    assert failed["status"] == "failed"
    assert agent._extractive_summary("Sentence one. Sentence two.", max_words=0) == ""
    assert agent._extractive_summary("   ", max_words=5) == ""


class _StoreSpy:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def store_result(self, **kwargs) -> None:
        self.results.append(kwargs)


@pytest.mark.parametrize("outcome", ["success", "failed", "raise"])
def test_batch_runner_aggregated_paths(outcome: str) -> None:
    store = _StoreSpy()
    agent = MagicMock()
    if outcome == "raise":
        agent.perform_task.side_effect = RuntimeError("model offline")
    else:
        agent.perform_task.return_value = {
            "status": outcome,
            "summary": "reference" if outcome == "success" else "failed",
            "mode": "fixture",
        }
    runner = BatchRunner(loader=MagicMock(), agent=agent, store=store)

    completed, failed, metrics = runner._run_aggregated(
        "run", [_record(), _record(1, reference="")], SummarizationConfig()
    )

    assert (completed, failed) == ((1, 0) if outcome == "success" else (0, 1))
    assert bool(metrics) is (outcome == "success")
    assert store.results[0]["record_index"] == -1


def test_batch_runner_single_converts_agent_exception_to_failed_result() -> None:
    store = _StoreSpy()
    agent = MagicMock()
    agent.name = "fixture-agent"
    agent.perform_task.side_effect = RuntimeError("model offline")
    runner = BatchRunner(loader=MagicMock(), agent=agent, store=store)

    completed, failed, metrics = runner._run_single(
        "run", [_record()], SummarizationConfig()
    )

    assert (completed, failed, metrics) == (0, 1, [])
    assert store.results[0]["status"] == "failed"
    assert store.results[0]["generated_summary"] == "model offline"


def test_batch_runner_empty_and_logger_paths(tmp_path) -> None:
    loader = MagicMock()
    loader.last_load_info = {"source": "fixture"}
    loader.load.side_effect = [[], [_record()], [_record()]]
    agent = MagicMock()
    agent.name = "fixture-agent"
    agent.perform_task.return_value = {
        "status": "failed",
        "summary": "no result",
        "mode": "fixture",
    }
    logger = MagicMock()
    store = RunStore(str(tmp_path / "runs.db"), str(tmp_path / "reports"))
    runner = BatchRunner(loader=loader, agent=agent, store=store, run_logger=logger)

    assert runner.run()["status"] == "empty"
    result = runner.run(SummarizationConfig(limit=1))
    assert result["status"] == "completed_with_errors"
    assert logger.log_event.call_count == 2
    logger.log_task_execution.assert_called_once()

    agent.perform_task.return_value = {
        "status": "success",
        "summary": "reference",
        "mode": "fixture",
    }
    batch_result = runner.run(
        SummarizationConfig(limit=1, aggregation=AggregationLevel.BATCH)
    )
    assert batch_result["status"] == "completed"


def test_batch_runner_does_not_initialize_agent_before_dataset_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = MagicMock()
    loader.load.side_effect = RuntimeError("dataset dependency failed")
    agent_factory = MagicMock()
    monkeypatch.setattr(
        batch_runner_module,
        "LegalSummarizerAgent",
        agent_factory,
    )

    runner = BatchRunner(loader=loader, store=MagicMock())
    with pytest.raises(RuntimeError, match="dataset dependency failed"):
        runner.run()

    agent_factory.assert_not_called()


def test_run_store_queries_migration_guard_and_missing_report(tmp_path) -> None:
    store = RunStore(str(tmp_path / "runs.db"), str(tmp_path / "reports"))
    store.start_run("one", "{}", "summary_en", "test", 0)
    store.start_run("two", "{}", "summary_en", "test", 0)

    assert [run["run_id"] for run in store.list_runs(limit=1)] == ["two"]
    assert [run["run_id"] for run in store.compare_runs(["missing", "one"])] == ["one"]
    with pytest.raises(ValueError, match="Unsupported migration table"):
        with sqlite3.connect(store.db_path) as conn:
            store._ensure_columns(conn, "rogue", {"column": "TEXT"})
    with pytest.raises(ValueError, match="Run missing not found"):
        store.write_report("missing")


class _CliLoader:
    SOURCES = LegalDatasetLoader.SOURCES

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def describe(self, **_kwargs):
        return {"source": "fixture", "record_count": 1}


class _CliStore:
    runs: list[dict] = []
    selected: dict | None = None
    results: list[dict] = []
    compared: list[dict] = []

    def list_runs(self):
        return self.runs

    def get_run(self, _run_id):
        return self.selected

    def get_results(self, _run_id, limit=5):
        return self.results[:limit]

    def compare_runs(self, _run_ids):
        return self.compared


def _patch_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "LegalDatasetLoader", _CliLoader)
    monkeypatch.setattr(cli, "RunStore", _CliStore)


def test_cli_inspection_commands(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _patch_cli(monkeypatch)
    cli.main(["--describe"])
    assert '"source": "fixture"' in capsys.readouterr().out

    _CliStore.runs = []
    cli.main(["--list-runs"])
    assert "No runs recorded" in capsys.readouterr().out
    _CliStore.runs = [
        {"run_id": "r1", "status": "completed", "total_records": 2, "duration_ms": 3}
    ]
    cli.main(["--list-runs"])
    assert "r1" in capsys.readouterr().out

    _CliStore.selected = None
    cli.main(["--show-run", "missing"])
    assert "not found" in capsys.readouterr().out
    _CliStore.selected = {"run_id": "r1", "status": "completed"}
    _CliStore.results = [
        {"record_index": 0, "status": "success", "generated_summary": "summary"}
    ]
    cli.main(["--show-run", "r1"])
    assert "First 1 results" in capsys.readouterr().out

    _CliStore.compared = []
    cli.main(["--compare", "missing"])
    assert "No matching runs" in capsys.readouterr().out
    _CliStore.compared = [{"run_id": "r1", "status": "completed"}]
    cli.main(["--compare", "r1"])
    assert "--- r1 ---" in capsys.readouterr().out


def test_cli_dependency_check_exits_before_loader_creation(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    status = {
        "ready": True,
        "python": {"executable": "/repo/.venv/bin/python"},
        "environment_file": {"token_configured": True, "token_source": "HF_TOKEN"},
    }
    loader = MagicMock()
    monkeypatch.setattr(cli, "huggingface_runtime_status", lambda: status)
    monkeypatch.setattr(cli, "LegalDatasetLoader", loader)

    cli.main(["--doctor"])

    assert json.loads(capsys.readouterr().out) == status
    loader.assert_not_called()

    monkeypatch.setattr(
        cli,
        "huggingface_runtime_status",
        lambda: {**status, "ready": False},
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--check-dependencies"])
    assert exc_info.value.code == 1


def test_cli_run_success_and_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _patch_cli(monkeypatch)
    run_logger = MagicMock()
    monkeypatch.setattr("src.utils.run_logger.init_run_logger", lambda: run_logger)
    runner = MagicMock()
    runner.run.return_value = {
        "run_id": "r1",
        "status": "completed",
        "failed": 0,
        "duration_ms": 1.0,
        "report_path": "report.md",
        "metrics": {"rouge1_f1": 1.0},
    }
    monkeypatch.setattr(cli, "BatchRunner", MagicMock(return_value=runner))

    cli.main(["--mode", "extractive", "--limit", "1"])
    assert "rouge1_f1" in capsys.readouterr().out
    run_logger.finalize_run.assert_called_once()

    runner.run.side_effect = RuntimeError("evaluation offline")
    with pytest.raises(SystemExit, match="Evaluation failed"):
        cli.main([])
    assert run_logger.finalize_run.call_count == 2


def test_cli_continues_when_core_run_logger_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cli(monkeypatch)

    def fail_logger():
        raise RuntimeError("logger offline")

    monkeypatch.setattr("src.utils.run_logger.init_run_logger", fail_logger)
    runner = MagicMock()
    runner.run.return_value = {
        "run_id": "r2",
        "status": "completed",
        "failed": 0,
        "duration_ms": 0.0,
        "metrics": {},
    }
    monkeypatch.setattr(cli, "BatchRunner", MagicMock(return_value=runner))

    cli.main(["--mode", "extractive", "--limit", "1"])

    assert cli.BatchRunner.call_args.kwargs["run_logger"] is None
