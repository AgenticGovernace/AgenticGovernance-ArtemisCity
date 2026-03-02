"""
Simple demonstration test for Artemis City guidelines.
This test demonstrates how to add a new test case and how the ATP parser works.
"""
import pytest
from agents.atp import ATPParser, ATPMode, ATPPriority

def test_atp_parser_demonstration():
    """Demonstrates that the ATPParser correctly identifies message fields."""
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
    """A trivial test to show how to use pytest assertions."""
    x = 10
    y = 20
    assert x + y == 30
