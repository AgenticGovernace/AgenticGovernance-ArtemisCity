"""Regression tests for MCP package import side effects."""

import subprocess
import sys
from pathlib import Path


def test_mcp_config_import_does_not_load_orchestrator():
    """Importing config should not trigger orchestrator's Obsidian imports."""
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import sys
import src.mcp.config

if "src.mcp.orchestrator" in sys.modules:
    raise SystemExit("src.mcp.config imported src.mcp.orchestrator")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
