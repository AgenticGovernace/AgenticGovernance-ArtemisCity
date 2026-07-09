"""Load Pakistani Legal Judgments dataset from local parquet or HuggingFace Hub.

The dataset (amjadali070/legal-judgements-en-ur-sd) is a single ``default``
config with a ``task`` column that labels each row as one of:
  repair, summary_en, summary_ur, summary_sd, translation_ur, translation_sd

Each record has: instruction, input, output, task.

For summarization we care about ``summary_en``, ``summary_ur``, ``summary_sd``
where ``input`` is the full judgment and ``output`` is the reference summary.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger("legal_summarization.dataset_loader")

# Default local clone of the HF repo inside the Exo Homelab folder.
_DEFAULT_LOCAL_PATH = os.getenv(
    "LEGAL_DATASET_PATH",
    "/Volumes/projects/GitHub/AgenticGovernance-ArtemisCity/src/Experiments/legal_summarization/legal-judgements-en-ur-sd",
)

HF_REPO_ID = "amjadali070/legal-judgements-en-ur-sd"


@dataclass(frozen=True)
class JudgmentRecord:
    """Single record from the legal judgments dataset."""

    index: int
    instruction: str
    input_text: str
    output_text: str
    task: str
    config: str  # e.g. "summary_en"
    split: str  # e.g. "train"


class LegalDatasetLoader:
    """Loads legal judgment data from local parquet files or the HF Hub.

    Strategy:
        1. Try loading from local parquet files under ``local_path/<config>/<split>-*.parquet``.
        2. If local files are empty stubs (< 1 KB) or missing, fall back to
           ``datasets.load_dataset`` from HuggingFace Hub.
    """

    SUMMARIZATION_CONFIGS = ("summary_en", "summary_ur", "summary_sd")
    ALL_CONFIGS = (
        "repair",
        "summary_en",
        "summary_ur",
        "summary_sd",
        "translation_ur",
        "translation_sd",
    )

    def __init__(self, local_path: Optional[str] = None):
        self.local_path = Path(local_path or _DEFAULT_LOCAL_PATH)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(
        self,
        config: str = "summary_en",
        split: str = "train",
        limit: Optional[int] = None,
    ) -> list[JudgmentRecord]:
        """Load records for a given config and split.

        Args:
            config: Dataset configuration name.
            split: Dataset split (train, validation, test).
            limit: Maximum records to return. ``None`` returns all.

        Returns:
            List of ``JudgmentRecord``.
        """
        if config not in self.ALL_CONFIGS:
            raise ValueError(
                f"Unknown config '{config}'. Choose from: {self.ALL_CONFIGS}"
            )

        records = list(self._iter_local(config, split, limit))
        if records:
            logger.info(
                "Loaded %d records from local parquet (%s/%s)",
                len(records),
                config,
                split,
            )
            return records

        logger.info(
            "Local parquet empty or missing for %s/%s — falling back to HuggingFace Hub",
            config,
            split,
        )
        records = list(self._iter_huggingface(config, split, limit))
        logger.info(
            "Loaded %d records from HuggingFace Hub (%s/%s)",
            len(records),
            config,
            split,
        )
        return records

    def available_configs(self) -> list[str]:
        """Return configs that have local data directories.

        Returns:
            list[str]: Dataset configuration names that are present under the local data path.
        """
        found = []
        for cfg in self.ALL_CONFIGS:
            cfg_dir = self.local_path / cfg
            if cfg_dir.is_dir():
                found.append(cfg)
        return found

    def describe(self, config: str = "summary_en", split: str = "train") -> dict:
        """Return quick metadata about a config and split without loading the full dataset.

        Args:
            config (str): Dataset configuration to inspect.
            split (str): Dataset split to inspect.

        Returns:
            dict: Lightweight metadata describing the selected dataset slice.
        """
        records = self.load(config, split, limit=5)
        return {
            "config": config,
            "split": split,
            "sample_count": len(records),
            "fields": ["instruction", "input_text", "output_text", "task"],
            "sample_input_length": len(records[0].input_text) if records else 0,
            "sample_output_length": len(records[0].output_text) if records else 0,
        }

    # ------------------------------------------------------------------
    # Local parquet loading
    # ------------------------------------------------------------------

    def _iter_local(
        self, config: str, split: str, limit: Optional[int]
    ) -> Iterator[JudgmentRecord]:
        cfg_dir = self.local_path / config
        if not cfg_dir.is_dir():
            return

        parquet_files = sorted(cfg_dir.glob(f"{split}-*.parquet"))
        if not parquet_files:
            # Also try without split prefix (some layouts use 0000-of-0001.parquet)
            parquet_files = sorted(cfg_dir.glob("*.parquet"))

        if not parquet_files:
            return

        # Skip stub files (the HF repo sometimes has tiny pointer files)
        real_files = [f for f in parquet_files if f.stat().st_size > 1024]
        if not real_files:
            return

        try:
            import pyarrow.parquet as pq
        except ImportError:
            logger.warning("pyarrow not installed — cannot read local parquet files")
            return

        count = 0
        for pf in real_files:
            table = pq.read_table(pf)
            for i in range(table.num_rows):
                if limit is not None and count >= limit:
                    return
                row = {col: table.column(col)[i].as_py() for col in table.column_names}
                yield JudgmentRecord(
                    index=count,
                    instruction=row.get("instruction", ""),
                    input_text=row.get("input", ""),
                    output_text=row.get("output", ""),
                    task=row.get("task", ""),
                    config=config,
                    split=split,
                )
                count += 1

    # ------------------------------------------------------------------
    # HuggingFace Hub fallback
    # ------------------------------------------------------------------

    # Map our config names to the ``task`` column values in the dataset.
    # Adjust if the actual task labels differ from the README.
    _TASK_LABEL_MAP: dict[str, str | None] = {
        "summary_en": "summary_en",
        "summary_ur": "summary_ur",
        "summary_sd": "summary_sd",
        "repair": "repair",
        "translation_ur": "translation_ur",
        "translation_sd": "translation_sd",
    }

    def _iter_huggingface(
        self, config: str, split: str, limit: Optional[int]
    ) -> Iterator[JudgmentRecord]:
        try:
            from datasets import load_dataset
        except ImportError:
            logger.error(
                "Neither local parquet files nor the `datasets` library are available. "
                "Install with: uv pip install datasets pyarrow"
            )
            return

        # The repo exposes a single 'default' config; we filter by task column.
        ds = load_dataset(HF_REPO_ID, split=split, trust_remote_code=True)

        task_label = self._TASK_LABEL_MAP.get(config, config)

        # Discover actual task labels on first load for debugging
        if hasattr(ds, "unique") and task_label:
            try:
                available_tasks = ds.unique("task")
                logger.info("Available task labels in dataset: %s", available_tasks)
                # Fuzzy match: if exact label missing, try case-insensitive / partial
                if task_label not in available_tasks:
                    for t in available_tasks:
                        if config.replace("_", " ") in t.lower() or config in t.lower():
                            logger.info(
                                "Mapped config '%s' to task label '%s'", config, t
                            )
                            task_label = t
                            break
            except Exception:
                pass

        count = 0
        for row in ds:
            # Filter to matching task
            if task_label and row.get("task", "") != task_label:
                continue
            if limit is not None and count >= limit:
                return
            yield JudgmentRecord(
                index=count,
                instruction=row.get("instruction", ""),
                input_text=row.get("input", ""),
                output_text=row.get("output", ""),
                task=row.get("task", ""),
                config=config,
                split=split,
            )
            count += 1
