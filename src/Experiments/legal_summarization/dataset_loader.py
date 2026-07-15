"""Dataset loading for the legal summarization evaluation pipeline.

The default source is ``amjadali070/legal-judgements-en-ur-sd`` on the
Hugging Face Hub, but every important loading option is configurable. Local
Parquet remains supported for offline/reproducible runs.

Authentication is intentionally resolved without accepting a token as a CLI
argument (command-line arguments are visible in process listings). The loader
uses, in order: an explicitly supplied programmatic token, ``HF_TOKEN``, the
legacy Artemis ``HUGGINGFACE_API_KEY``, or a hidden runtime prompt when the
caller explicitly requests one.
"""

from __future__ import annotations

import getpass
import importlib
import logging
import os
import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Callable, Iterator, Optional

logger = logging.getLogger("legal_summarization.dataset_loader")

HF_REPO_ID = "amjadali070/legal-judgements-en-ur-sd"
HF_REVISION = "main"
TOKEN_ENV_VARS = ("HF_TOKEN", "HUGGINGFACE_API_KEY")
PYTHON_REQUIREMENT = ">=3.12,<3.13"
HF_RUNTIME_DEPENDENCIES = (
    ("datasets", "datasets"),
    ("pyarrow", "pyarrow"),
    ("huggingface_hub", "huggingface-hub"),
)
DOTENV_DEPENDENCY = ("dotenv", "python-dotenv")


def _dependency_status(module_name: str, distribution_name: str) -> dict:
    """Return import and version evidence without exposing environment values."""
    try:
        version = metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        version = None

    try:
        importlib.import_module(module_name)
    except Exception as exc:
        detail = " ".join(str(exc).split()) or "no error detail"
        return {
            "distribution": distribution_name,
            "version": version,
            "importable": False,
            "error": f"{type(exc).__name__}: {detail}",
        }

    return {
        "distribution": distribution_name,
        "version": version,
        "importable": True,
        "error": None,
    }


def huggingface_runtime_status() -> dict:
    """Describe the active Hugging Face runtime without printing token values."""
    python_supported = (3, 12) <= sys.version_info[:2] < (3, 13)
    dependencies = {
        module_name: _dependency_status(module_name, distribution_name)
        for module_name, distribution_name in HF_RUNTIME_DEPENDENCIES
    }
    dotenv = _dependency_status(*DOTENV_DEPENDENCY)
    token, token_source = resolve_hf_token()
    repo_root = Path(__file__).resolve().parents[3]
    repo_interpreter = (
        repo_root
        / ".venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )

    return {
        "ready": python_supported
        and all(item["importable"] for item in dependencies.values()),
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "supported": python_supported,
            "required": PYTHON_REQUIREMENT,
            "repo_interpreter": str(repo_interpreter),
        },
        "dependencies": dependencies,
        "environment_file": {
            "python_dotenv": dotenv,
            "token_configured": token is not None,
            "token_source": token_source,
        },
    }


def require_huggingface_runtime() -> dict:
    """Fail with the exact interpreter and broken imports when Hub use is unsafe."""
    status = huggingface_runtime_status()
    if status["ready"]:
        return status

    python = status["python"]
    problems = []
    if not python["supported"]:
        problems.append(
            f"Python {python['version']} is unsupported; required {python['required']}"
        )

    failed_imports = [
        f"{name} ({details['error']})"
        for name, details in status["dependencies"].items()
        if not details["importable"]
    ]
    if failed_imports:
        problems.append("dependency import failures: " + "; ".join(failed_imports))

    detail = ". ".join(problems)
    raise RuntimeError(
        "Hugging Face runtime check failed under "
        f"'{python['executable']}' ({detail}). Run `make install` from the repository "
        'root, then launch with `make legal-summarization ARGS="--dataset-source '
        'hub --streaming --describe"`. Do not use bare `python` or `python3`, '
        "which may select a different interpreter."
    )


@dataclass(frozen=True)
class JudgmentRecord:
    """One source/reference pair prepared for evaluation."""

    index: int
    instruction: str
    input_text: str
    output_text: str
    task: str
    config: str
    split: str


def resolve_hf_token(
    explicit_token: Optional[str] = None,
    *,
    prompt: bool = False,
    prompt_fn: Optional[Callable[[str], str]] = None,
) -> tuple[Optional[str], str]:
    """Resolve a Hub token without logging or persisting its value.

    Returns:
        ``(token, source)`` where source is one of ``explicit``, ``HF_TOKEN``,
        ``HUGGINGFACE_API_KEY``, ``prompt``, or ``none``.
    """
    if explicit_token and explicit_token.strip():
        return explicit_token.strip(), "explicit"

    for env_name in TOKEN_ENV_VARS:
        value = os.getenv(env_name, "").strip()
        if value:
            return value, env_name

    if not prompt:
        return None, "none"

    if prompt_fn is None:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Cannot request a Hugging Face token without an interactive terminal. "
                "Set HF_TOKEN in the repository .env file instead."
            )
        prompt_fn = getpass.getpass

    value = prompt_fn("Hugging Face token (input hidden): ").strip()
    if not value:
        raise RuntimeError("No Hugging Face token was provided.")
    return value, "prompt"


class LegalDatasetLoader:
    """Load configurable source/reference records from local files or the Hub."""

    SUMMARIZATION_CONFIGS = ("summary_en", "summary_ur", "summary_sd")
    ALL_CONFIGS = (
        "repair",
        "repair_en",
        "summary_en",
        "summary_ur",
        "summary_sd",
        "translation_ur",
        "translation_sd",
    )
    SOURCES = ("auto", "local", "hub")

    def __init__(
        self,
        local_path: Optional[str] = None,
        *,
        source: str = "auto",
        dataset_id: Optional[str] = None,
        dataset_name: Optional[str] = None,
        revision: Optional[str] = None,
        cache_dir: Optional[str] = None,
        data_files: Optional[list[str]] = None,
        streaming: bool = False,
        token: Optional[str] = None,
        prompt_for_token: bool = False,
        input_column: str = "input",
        reference_column: str = "output",
        instruction_column: str = "instruction",
        task_column: str = "task",
    ) -> None:
        normalized_source = source.strip().lower()
        if normalized_source not in self.SOURCES:
            raise ValueError(f"source must be one of: {', '.join(self.SOURCES)}")

        configured_local = local_path or os.getenv("LEGAL_DATASET_PATH")
        self.local_path = (
            Path(configured_local).expanduser() if configured_local else None
        )
        self.source = normalized_source
        self.dataset_id = (
            dataset_id or os.getenv("LEGAL_DATASET_ID") or HF_REPO_ID
        ).strip()
        self.dataset_name = dataset_name or os.getenv("LEGAL_DATASET_NAME") or None
        self._resolved_dataset_name = self.dataset_name
        self.revision = (
            revision or os.getenv("LEGAL_DATASET_REVISION") or HF_REVISION
        ).strip()
        self.cache_dir = cache_dir or os.getenv("HF_DATASETS_CACHE") or None
        self.data_files = list(data_files or []) or None
        self.streaming = bool(streaming)
        self._explicit_token = token
        self.prompt_for_token = bool(prompt_for_token)
        self.input_column = input_column
        self.reference_column = reference_column
        self.instruction_column = instruction_column
        self.task_column = task_column
        self.last_load_info: dict = self._source_info(source_used=None)

    def load(
        self,
        config: Optional[str] = "summary_en",
        split: str = "train",
        limit: Optional[int] = None,
    ) -> list[JudgmentRecord]:
        """Load one dataset slice and normalize its source/reference columns."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1 when provided")

        if self.source in {"auto", "local"}:
            records = list(self._iter_local(config, split, limit))
            if records:
                self.last_load_info = self._source_info(
                    source_used="local", record_count=len(records)
                )
                logger.info("Loaded %d records from local Parquet", len(records))
                return records
            if self.source == "local":
                self.last_load_info = self._source_info(
                    source_used="local", record_count=0
                )
                return []

        records = list(self._iter_huggingface(config, split, limit))
        self.last_load_info = self._source_info(
            source_used="hub",
            record_count=len(records),
            token_source=self.last_load_info.get("token_source", "none"),
        )
        logger.info(
            "Loaded %d records from Hugging Face dataset %s at %s",
            len(records),
            self.dataset_id,
            self.revision,
        )
        return records

    def available_configs(self) -> list[str]:
        """Return task/config directories available under the local source."""
        if self.local_path is None or not self.local_path.is_dir():
            return []
        return [cfg for cfg in self.ALL_CONFIGS if (self.local_path / cfg).is_dir()]

    def describe(
        self,
        config: Optional[str] = "summary_en",
        split: str = "train",
    ) -> dict:
        """Load a small sample and return source/schema metadata without secrets."""
        records = self.load(config, split, limit=5)
        return {
            **self.last_load_info,
            "task_filter": config,
            "split": split,
            "sample_count": len(records),
            "fields": {
                "instruction": self.instruction_column,
                "input": self.input_column,
                "reference": self.reference_column,
                "task": self.task_column,
            },
            "sample_input_length": len(records[0].input_text) if records else 0,
            "sample_reference_length": len(records[0].output_text) if records else 0,
        }

    def _source_info(
        self,
        *,
        source_used: Optional[str],
        record_count: Optional[int] = None,
        token_source: str = "unresolved",
    ) -> dict:
        return {
            "source": source_used or self.source,
            "dataset_id": self.dataset_id,
            "dataset_name": self._resolved_dataset_name,
            "revision": self.revision,
            "streaming": self.streaming,
            "local_path": str(self.local_path) if self.local_path else None,
            "cache_dir": self.cache_dir,
            "token_source": token_source,
            "authenticated": token_source not in {"none", "unresolved"},
            "record_count": record_count,
        }

    def _iter_local(
        self,
        config: Optional[str],
        split: str,
        limit: Optional[int],
    ) -> Iterator[JudgmentRecord]:
        if self.local_path is None or not self.local_path.exists():
            return

        base = self.local_path
        if base.is_file():
            parquet_files = [base] if base.suffix == ".parquet" else []
        else:
            config_dir = base / config if config and (base / config).is_dir() else base
            parquet_files = sorted(config_dir.glob(f"{split}-*.parquet"))
            if not parquet_files:
                parquet_files = sorted(config_dir.glob("*.parquet"))

        real_files = [path for path in parquet_files if path.stat().st_size > 1024]
        if not real_files:
            return

        try:
            import pyarrow.parquet as pq
        except ImportError:
            logger.warning("pyarrow is required to read local Parquet files")
            return

        count = 0
        for parquet_file in real_files:
            table = pq.read_table(parquet_file)
            for row_index in range(table.num_rows):
                row = {
                    column: table.column(column)[row_index].as_py()
                    for column in table.column_names
                }
                record = self._record_from_row(row, count, config, split)
                if record is None:
                    continue
                yield record
                count += 1
                if limit is not None and count >= limit:
                    return

    def _iter_huggingface(
        self,
        config: Optional[str],
        split: str,
        limit: Optional[int],
    ) -> Iterator[JudgmentRecord]:
        require_huggingface_runtime()
        load_dataset = importlib.import_module("datasets").load_dataset

        self._resolved_dataset_name = self.dataset_name

        token, token_source = resolve_hf_token(
            self._explicit_token,
            prompt=self.prompt_for_token,
        )
        self.last_load_info = self._source_info(
            source_used="hub", token_source=token_source
        )

        try:
            dataset = load_dataset(
                path=self.dataset_id,
                name=self._resolved_dataset_name,
                split=split,
                revision=self.revision,
                token=token,
                streaming=self.streaming,
                cache_dir=self.cache_dir,
                data_files=self.data_files,
            )
        except Exception as exc:
            message = str(exc).lower()
            if any(marker in message for marker in ("401", "403", "gated", "token")):
                raise RuntimeError(
                    "Hugging Face authentication failed. Set HF_TOKEN in .env or "
                    "rerun with --prompt-for-hf-token."
                ) from exc
            raise RuntimeError(
                f"Unable to load Hugging Face dataset '{self.dataset_id}' "
                f"at revision '{self.revision}': {exc}"
            ) from exc

        count = 0
        for row in dataset:
            record = self._record_from_row(row, count, config, split)
            if record is None:
                continue
            yield record
            count += 1
            if limit is not None and count >= limit:
                return

    def _record_from_row(
        self,
        row: dict,
        index: int,
        config: Optional[str],
        split: str,
    ) -> Optional[JudgmentRecord]:
        if self.input_column not in row:
            available = ", ".join(sorted(str(key) for key in row))
            raise ValueError(
                f"Input column '{self.input_column}' is absent. Available columns: {available}"
            )

        task_value = str(row.get(self.task_column) or "")
        if config:
            if self.task_column not in row:
                raise ValueError(
                    f"Task filter '{config}' was requested but column "
                    f"'{self.task_column}' is absent. Use --task-filter '' to disable it."
                )
            if task_value != config:
                return None

        return JudgmentRecord(
            index=index,
            instruction=str(row.get(self.instruction_column) or ""),
            input_text=str(row.get(self.input_column) or ""),
            output_text=str(row.get(self.reference_column) or ""),
            task=task_value,
            config=str(config or self.dataset_name or "all"),
            split=split,
        )
