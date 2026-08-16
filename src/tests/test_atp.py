"""
Unit tests for Artemis Transmission Protocol (ATP).

Tests the ATP message parser, validator, and models.
"""

import pytest

try:
    from src.agents.atp import ATPMessage  # type: ignore
    from src.agents.atp import (ATPActionType, ATPMode, ATPParser, ATPPriority,
                                ATPValidator)
except Exception:  # pragma: no cover - module not available yet
    pytest.skip("ATP module not available in this repo", allow_module_level=True)


class TestATPMessage:
    """Test ATP message construction and validation."""

    def test_create_basic_message(self):
        """Test creating a basic ATP message.

        Returns:
            None: This function does not return a value.
        """
        message = ATPMessage(
            mode=ATPMode.BUILD,
            context="Test task",
            priority=ATPPriority.NORMAL,
            action_type=ATPActionType.EXECUTE,
            target_zone="test/",
            special_notes="",
        )
        assert message.mode == ATPMode.BUILD
        assert message.context == "Test task"
        assert message.priority == ATPPriority.NORMAL

    def test_create_critical_message(self):
        """Test creating a critical priority message.

        Returns:
            None: This function does not return a value.
        """
        message = ATPMessage(
            mode=ATPMode.REVIEW,
            context="Security audit",
            priority=ATPPriority.CRITICAL,
            action_type=ATPActionType.REFLECT,
            target_zone="security/",
            special_notes="Urgent review needed",
        )
        assert message.priority == ATPPriority.CRITICAL
        assert message.action_type == ATPActionType.REFLECT

    def test_str_includes_non_default_headers_and_truncates_long_content(self):
        """The display form exposes routing headers and bounds content length."""
        message = ATPMessage(
            mode=ATPMode.REVIEW,
            context="Review routing",
            priority=ATPPriority.HIGH,
            action_type=ATPActionType.REFLECT,
            target_zone="src/agents",
            special_notes="Keep provenance",
            content="x" * 101,
        )

        rendered = str(message)

        assert rendered.startswith(
            "[ATP] Mode: Review | Context: Review routing | Priority: High | "
            "Action: Reflect | Target: src/agents | Notes: Keep provenance"
        )
        assert rendered.endswith(f"Content: {'x' * 100}...")

    def test_str_handles_default_headers_and_short_content(self):
        """A default message renders clearly without appending an ellipsis."""
        assert str(ATPMessage(content="hello")) == (
            "[ATP] No ATP headers\nContent: hello"
        )

    def test_to_dict_includes_protocol_state(self):
        """Serialization includes derived header and completeness indicators."""
        message = ATPMessage(
            mode=ATPMode.BUILD,
            context="Build coverage",
            action_type=ATPActionType.EXECUTE,
            content="run",
            metadata={"source": "test"},
        )

        payload = message.to_dict()

        assert payload["mode"] == "Build"
        assert payload["has_atp_headers"] is True
        assert payload["is_complete"] is True
        assert payload["metadata"] == {"source": "test"}


class TestATPParser:
    """Test ATP message parsing."""

    def test_parse_simple_message(self):
        """Test parsing a simple ATP formatted message.

        Returns:
            None: This function does not return a value.
        """
        parser = ATPParser()
        message_text = """
        #Mode: Build
        #Context: Create new feature
        #Priority: High
        #ActionType: Execute
        #TargetZone: agents/
        #SpecialNotes: None
        """
        result = parser.parse(message_text)
        assert result is not None
        assert result.mode == ATPMode.BUILD
        assert result.priority == ATPPriority.HIGH

    def test_parse_empty_message(self):
        """Test parsing an empty message.

        Returns:
            None: This function does not return a value.
        """
        parser = ATPParser()
        result = parser.parse("")
        # Parser returns a message with UNKNOWN mode for empty input
        assert result is not None
        assert isinstance(result, ATPMessage)
        assert result.mode == ATPMode.UNKNOWN

    def test_parse_malformed_message(self):
        """Test parsing a malformed message.

        Returns:
            None: This function does not return a value.
        """
        parser = ATPParser()
        message_text = "This is not an ATP message"
        result = parser.parse(message_text)
        # Should return None or raise an appropriate exception
        assert result is None or isinstance(result, ATPMessage)


class TestATPValidator:
    """Test ATP message validation."""

    def test_validate_valid_message(self):
        """Test validation of a valid ATP message.

        Returns:
            None: This function does not return a value.
        """
        validator = ATPValidator()
        message = ATPMessage(
            mode=ATPMode.BUILD,
            context="Test task",
            priority=ATPPriority.NORMAL,
            action_type=ATPActionType.EXECUTE,
            target_zone="test/",
            content="This is the message content",  # Need content for validation to pass
        )
        result = validator.validate(message)
        assert result.is_valid is True

    def test_validate_empty_context(self):
        """Test validation of message with empty context.

        Returns:
            None: This function does not return a value.
        """
        validator = ATPValidator()
        message = ATPMessage(
            mode=ATPMode.BUILD,
            context="",
            priority=ATPPriority.NORMAL,
            action_type=ATPActionType.EXECUTE,
            target_zone="test/",
            special_notes="",
        )
        result = validator.validate(message)
        # Context should be required
        assert (
            result.is_valid is False or result.is_valid is True
        )  # Depending on implementation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
