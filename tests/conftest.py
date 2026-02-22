"""Shared pytest fixtures for Artemis City tests.

This module provides common fixtures used across unit, integration,
and end-to-end tests.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add project root and src directory to path for imports
_project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, _project_root)
sys.path.insert(0, str(Path(_project_root) / "src"))


# ============================================
# ATP MESSAGE FIXTURES
# ============================================


@pytest.fixture
def sample_atp_hash():
    """Sample ATP message in hash format.

    Returns:
        str: ATP message using #Tag: syntax
    """
    return """#Mode: Build
#Context: Implementing new feature
#Priority: High
#ActionType: Execute
#TargetZone: /agents/

Build the new agent component."""


@pytest.fixture
def sample_atp_bracket():
    """Sample ATP message in bracket format.

    Returns:
        str: ATP message using [[Tag]]: syntax
    """
    return """[[Mode]]: Review
[[Context]]: Code review
[[ActionType]]: Reflect

Review the implementation."""


@pytest.fixture
def sample_atp_empty():
    """Empty ATP message for edge case testing.

    Returns:
        str: Empty string
    """
    return ""


@pytest.fixture
def sample_atp_malformed():
    """Malformed ATP message for error handling tests.

    Returns:
        str: Invalid ATP message
    """
    return "This is not an ATP formatted message"


@pytest.fixture
def sample_atp_partial():
    """Partial ATP message with only some headers.

    Returns:
        str: ATP message with missing required fields
    """
    return """#Mode: Build
#Context: Partial message

Some content here."""


# ============================================
# PROJECT STRUCTURE FIXTURES
# ============================================


@pytest.fixture
def project_structure(tmp_path):
    """Create temporary project structure for testing.

    Args:
        tmp_path: pytest's temporary path fixture

    Returns:
        Path: Root path of the test project structure
    """
    # Create directories
    (tmp_path / "agents").mkdir()
    (tmp_path / "codex").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "tests").mkdir()

    # Create configuration files
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'test-project'\nversion = '0.1.0'"
    )
    (tmp_path / "codex.md").write_text("# Project Instructions\n\nTest instructions.")
    (tmp_path / "README.md").write_text("# Test Project\n\nTest readme.")

    # Create sample agent file
    (tmp_path / "agents" / "test_agent.py").write_text(
        '"""Test agent."""\n\nclass TestAgent:\n    pass'
    )

    return tmp_path


@pytest.fixture
def minimal_project(tmp_path):
    """Create minimal project structure.

    Args:
        tmp_path: pytest's temporary path fixture

    Returns:
        Path: Root path of minimal project
    """
    (tmp_path / "main.py").write_text("print('hello')")
    return tmp_path


# ============================================
# MOCK MEMORY CLIENT FIXTURES
# ============================================


@pytest.fixture
def mock_memory_client(mocker):
    """Mock MemoryClient for tests without server dependency.

    Args:
        mocker: pytest-mock fixture

    Returns:
        MagicMock: Mocked MemoryClient instance
    """
    mock = mocker.MagicMock()

    # Configure health check
    mock.health_check.return_value = True

    # Configure get_context
    mock.get_context.return_value = mocker.MagicMock(
        success=True,
        data={"content": "test content"},
        error=None,
        status_code=200,
    )

    # Configure append_context
    mock.append_context.return_value = mocker.MagicMock(
        success=True,
        data=None,
        message="Content appended successfully",
        error=None,
        status_code=200,
    )

    # Configure search_notes
    mock.search_notes.return_value = mocker.MagicMock(
        success=True,
        data={"results": []},
        error=None,
        status_code=200,
    )

    return mock


@pytest.fixture
def mock_memory_client_offline(mocker):
    """Mock MemoryClient simulating offline/unreachable server.

    Args:
        mocker: pytest-mock fixture

    Returns:
        MagicMock: Mocked MemoryClient that fails requests
    """
    mock = mocker.MagicMock()

    mock.health_check.return_value = False

    mock.get_context.return_value = mocker.MagicMock(
        success=False,
        data=None,
        error="Connection refused",
        status_code=0,
    )

    return mock


# ============================================
# TRUST SCORE FIXTURES
# ============================================


@pytest.fixture
def sample_trust_scores():
    """Sample trust score data for various agents.

    Returns:
        dict: Agent names mapped to trust scores (0.0-1.0)
    """
    return {
        "artemis": 0.95,
        "copilot": 0.90,
        "pack_rat": 0.85,
        "codex_daemon": 0.80,
        "new_agent": 0.50,
        "untrusted": 0.20,
    }


@pytest.fixture
def trust_score_high():
    """High trust score for trusted agent.

    Returns:
        float: Trust score above threshold
    """
    return 0.95


@pytest.fixture
def trust_score_low():
    """Low trust score for untrusted agent.

    Returns:
        float: Trust score below threshold
    """
    return 0.25


@pytest.fixture
def trust_score_threshold():
    """Trust score at threshold boundary.

    Returns:
        float: Trust score at threshold
    """
    return 0.50


# ============================================
# AGENT FIXTURES
# ============================================


@pytest.fixture
def mock_agent(mocker):
    """Create a mock agent for testing.

    Args:
        mocker: pytest-mock fixture

    Returns:
        MagicMock: Mocked agent instance
    """
    mock = mocker.MagicMock()
    mock.name = "test_agent"
    mock.trust_score = 0.75
    mock.is_active = True
    return mock


# ============================================
# ENVIRONMENT FIXTURES
# ============================================


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables for testing.

    Args:
        monkeypatch: pytest's monkeypatch fixture

    Returns:
        dict: The environment variables that were set
    """
    env_vars = {
        "MCP_BASE_URL": "http://localhost:3000",
        "MCP_API_KEY": "test-api-key-12345",
        "ARTEMIS_LOG_LEVEL": "DEBUG",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def clean_env(monkeypatch):
    """Remove potentially interfering environment variables.

    Args:
        monkeypatch: pytest's monkeypatch fixture
    """
    vars_to_remove = ["MCP_BASE_URL", "MCP_API_KEY", "ARTEMIS_LOG_LEVEL"]
    for var in vars_to_remove:
        monkeypatch.delenv(var, raising=False)


# ============================================
# PYTEST MARKERS CONFIGURATION
# ============================================


def pytest_configure(config):
    """Configure custom pytest markers.

    Args:
        config: pytest configuration object
    """
    config.addinivalue_line("markers", "unit: Unit tests for individual components")
    config.addinivalue_line(
        "markers", "integration: Integration tests for module interaction"
    )
    config.addinivalue_line("markers", "e2e: End-to-end workflow tests")
    config.addinivalue_line("markers", "slow: Tests that take longer to run")
    config.addinivalue_line("markers", "requires_server: Tests that need MCP server")
