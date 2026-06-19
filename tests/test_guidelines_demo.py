"""
Simple demonstration test for Artemis City guidelines.
This test demonstrates how to add a new test case and how the ATP parser works.
"""

import pytest

from src.agents.atp import ATPMode, ATPParser, ATPPriority


def test_atp_parser_demonstration():
    """Demonstrates that the ATPParser correctly identifies message fields.

    Returns:
        None: This function does not return a value.
    """
    parser = ATPParser()
    atp_text = """
    #Mode: Build
    #Context: Create a simple demonstration test
    #Priority: Normal
    #ActionType: Execute
    #TargetZone: tests/
    """
    message = parser.parse(atp_text)

    # Assertions to verify the parser works as expected
    assert message.mode == ATPMode.BUILD
    assert message.priority == ATPPriority.NORMAL
    assert "demonstration" in message.context.lower()


def test_simple_logic_check():
    """A trivial test to show how to use pytest assertions.

    Returns:
        None: This function does not return a value.
    """
    x = 10
    y = 20
    assert x + y == 30
