"""Fresh-process import-boundary tests for the canonical ATP core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_fresh_process(tmp_path: Path, source: str) -> dict[str, Any]:
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(REPOSITORY_ROOT)
        if not existing_path
        else f"{REPOSITORY_ROOT}{os.pathsep}{existing_path}"
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["ARTEMIS_LOG_DIR"] = str(tmp_path / "logs")
    environment["ARTEMIS_LOG_FILE"] = str(tmp_path / "logs" / "mcp_obsidian.log")
    environment.pop("PROMETHEUS_MULTIPROC_DIR", None)
    environment.pop("prometheus_multiproc_dir", None)
    completed = subprocess.run(
        [sys.executable, "-c", dedent(source)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def test_validation_import_has_no_transport_or_observability_side_effects(
    tmp_path: Path,
) -> None:
    payload = _run_fresh_process(
        tmp_path,
        """
        import json
        import logging
        import os
        import sys

        from prometheus_client import REGISTRY

        def state():
            return {
                "handlers": [type(handler).__name__ for handler in logging.getLogger().handlers],
                "log_file": os.path.exists(
                    os.path.join(os.environ["ARTEMIS_LOG_DIR"], "mcp_obsidian.log")
                ),
                "metrics": sorted(
                    name
                    for name in REGISTRY._names_to_collectors
                    if name.startswith("artemis_atp_parse")
                ),
                "routing": sorted(
                    name
                    for name in sys.modules
                    if name == "src.routing" or name.startswith("src.routing.")
                ),
            }

        before = state()
        import src.validation
        after = state()
        print(json.dumps({"after": after, "before": before}, sort_keys=True))
        """,
    )

    expected = {"handlers": [], "log_file": False, "metrics": [], "routing": []}
    assert payload["before"] == expected
    assert payload["after"] == expected


def test_prometheus_guard_import_does_not_configure_logging(tmp_path: Path) -> None:
    payload = _run_fresh_process(
        tmp_path,
        """
        import json
        import logging
        import os

        def state():
            return {
                "handlers": [type(handler).__name__ for handler in logging.getLogger().handlers],
                "log_file": os.path.exists(
                    os.path.join(os.environ["ARTEMIS_LOG_DIR"], "mcp_obsidian.log")
                ),
            }

        before = state()
        from src.utils.prometheus_guard import safe_metric
        after = state()
        print(json.dumps({"after": after, "before": before, "safe_metric": callable(safe_metric)}))
        """,
    )

    expected = {"handlers": [], "log_file": False}
    assert payload["before"] == expected
    assert payload["after"] == expected
    assert payload["safe_metric"] is True


def test_lazy_package_exports_remain_usable(tmp_path: Path) -> None:
    payload = _run_fresh_process(
        tmp_path,
        """
        import json
        import logging

        from src.agents.atp import (
            ATPActionType,
            ATPMessage,
            ATPMode,
            ATPParser,
            ATPPriority,
            ATPValidationResult,
            ATPValidator,
            ValidationResult,
            infer_capability,
            resolve_task_context,
        )
        from src.utils import get_run_logger, init_run_logger, logger, sanitize_for_log

        message = ATPMessage(
            mode=ATPMode.BUILD,
            context="Use the package exports",
            priority=ATPPriority.NORMAL,
            action_type=ATPActionType.EXECUTE,
            content="body",
        )
        parsed = ATPParser().parse(
            "#Mode: Build" + chr(10) + "#Context: parser export"
        )
        resolved = resolve_task_context({"content": "ordinary task"})
        print(json.dumps({
            "action": infer_capability(message),
            "alias": ATPValidationResult is ValidationResult,
            "logger": isinstance(logger, logging.Logger),
            "parsed_mode": parsed.mode.value,
            "resolved": resolved,
            "sanitized": sanitize_for_log("safe value"),
            "validator": ATPValidator().validate(message).is_valid,
            "run_logger_exports": callable(get_run_logger) and callable(init_run_logger),
        }, sort_keys=True))
        """,
    )

    assert payload == {
        "action": "llm_chat",
        "alias": True,
        "logger": True,
        "parsed_mode": "Build",
        "resolved": {"content": "ordinary task"},
        "run_logger_exports": True,
        "sanitized": "safe value",
        "validator": True,
    }


def test_fresh_process_isolates_inherited_logging_and_metric_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inherited_root = tmp_path.parent / f"{tmp_path.name}-inherited"
    inherited_log = inherited_root / "operator.log"
    inherited_metrics = inherited_root / "metrics"
    inherited_legacy_metrics = inherited_root / "legacy-metrics"
    inherited_metrics.mkdir(parents=True)
    inherited_legacy_metrics.mkdir()
    monkeypatch.setenv("ARTEMIS_LOG_FILE", str(inherited_log))
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(inherited_metrics))
    monkeypatch.setenv("prometheus_multiproc_dir", str(inherited_legacy_metrics))

    payload = _run_fresh_process(
        tmp_path,
        """
        import json
        import os
        from pathlib import Path

        from src.agents.atp.atp_parser import ATPParser
        from src.utils import logger

        _, metrics = ATPParser().parse_with_metrics(
            "#Mode: Build" + chr(10) + "#Context: isolate child paths"
        )
        log_file = Path(os.environ["ARTEMIS_LOG_FILE"])
        print(json.dumps({
            "legacy_multiproc_dir": os.environ.get("prometheus_multiproc_dir"),
            "log_file": str(log_file.resolve()),
            "log_file_exists": log_file.is_file(),
            "logger_name": logger.name,
            "metrics_format": metrics["format_detected"],
            "multiproc_dir": os.environ.get("PROMETHEUS_MULTIPROC_DIR"),
        }, sort_keys=True))
        """,
    )

    expected_log = (tmp_path / "logs" / "mcp_obsidian.log").resolve()
    assert payload == {
        "legacy_multiproc_dir": None,
        "log_file": str(expected_log),
        "log_file_exists": True,
        "logger_name": "MCP_System",
        "metrics_format": "hash",
        "multiproc_dir": None,
    }
    assert inherited_log.exists() is False
    assert list(inherited_metrics.iterdir()) == []
    assert list(inherited_legacy_metrics.iterdir()) == []


def test_parser_metrics_are_lazy_and_reimport_safe(tmp_path: Path) -> None:
    payload = _run_fresh_process(
        tmp_path,
        """
        import importlib
        import json
        import sys

        from prometheus_client import REGISTRY

        def metric_names():
            return sorted(
                name
                for name in REGISTRY._names_to_collectors
                if name.startswith("artemis_atp_parse")
            )

        before = metric_names()
        from src.agents.atp.atp_parser import ATPParser
        after_import = metric_names()
        parser = ATPParser()
        plain = parser.parse("plain parser content")
        after_plain_parse = metric_names()
        _, first_metrics = parser.parse_with_metrics(
            "#Mode: Build" + chr(10) + "#Context: register metrics"
        )
        after_metrics = metric_names()
        first_count = REGISTRY.get_sample_value(
            "artemis_atp_parse_total",
            {"format": "hash", "has_headers": "true"},
        )

        sys.modules.pop("src.agents.atp.atp_parser", None)
        reimported = importlib.import_module("src.agents.atp.atp_parser")
        reimported.ATPParser().parse("plain parser content after reimport")
        after_reimport_plain_parse = metric_names()
        _, second_metrics = reimported.ATPParser().parse_with_metrics(
            "#Mode: Build" + chr(10) + "#Context: register metrics"
        )
        second_count = REGISTRY.get_sample_value(
            "artemis_atp_parse_total",
            {"format": "hash", "has_headers": "true"},
        )
        print(json.dumps({
            "after_import": after_import,
            "after_metrics": after_metrics,
            "after_plain_parse": after_plain_parse,
            "after_reimport_plain_parse": after_reimport_plain_parse,
            "before": before,
            "first_count": first_count,
            "first_metrics": first_metrics,
            "plain_content": plain.content,
            "second_count": second_count,
            "second_metrics": second_metrics,
        }, sort_keys=True))
        """,
    )

    assert payload["before"] == []
    assert payload["after_import"] == []
    assert payload["after_plain_parse"] == []
    assert payload["plain_content"] == "plain parser content"
    assert payload["after_metrics"]
    assert payload["after_reimport_plain_parse"] == payload["after_metrics"]
    assert payload["first_metrics"]["format_detected"] == "hash"
    assert payload["second_metrics"]["format_detected"] == "hash"
    assert payload["first_count"] is not None
    assert payload["second_count"] == payload["first_count"] + 1
