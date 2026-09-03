import pytest
from unittest.mock import patch, mock_open
from app.kernel.agent_router import AgentRouter

@patch("os.path.exists", return_value=True)
def test_load_config_error_handling(mock_exists, capsys):
    """Test that AgentRouter handles exceptions during config loading gracefully."""
    with patch('builtins.open', mock_open()) as m_open:
        m_open.side_effect = Exception("Mocked exception")

        # Initialize AgentRouter, which calls load_config
        router = AgentRouter(config_path="dummy_path.yaml")

        # Check that routes fall back to empty dict
        assert router.routes == {}

        # Check that the error message was printed
        captured = capsys.readouterr()
        assert "[Router] Error loading config: Mocked exception" in captured.out

def test_load_config_invalid_yaml(capsys):
    """Test that AgentRouter handles invalid YAML gracefully."""
    with patch("os.path.exists", return_value=True):
        with patch('builtins.open', mock_open(read_data="invalid: yaml: :")):
            router = AgentRouter(config_path="dummy_path.yaml")
            assert router.routes == {}
            captured = capsys.readouterr()
            assert "[Router] Error loading config:" in captured.out
