"""Legal Judgment Summarization — Daemon Experiment.

Batch-summarizes Pakistani legal judgments (en/ur/sd) via the Agentic
Governance pipeline, routing inference through the local EXO cluster.
"""

from .batch_runner import BatchRunner
from .dataset_loader import LegalDatasetLoader, resolve_hf_token
from .evaluation import aggregate_metrics, evaluate_summary
from .legal_summarizer_agent import LegalSummarizerAgent
from .run_store import RunStore
from .summarization_config import SummarizationConfig

__all__ = [
    "SummarizationConfig",
    "LegalDatasetLoader",
    "LegalSummarizerAgent",
    "BatchRunner",
    "RunStore",
    "resolve_hf_token",
    "evaluate_summary",
    "aggregate_metrics",
]
