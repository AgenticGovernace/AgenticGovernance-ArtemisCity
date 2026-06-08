"""Tests for the Artemis persona (src/agents/artemis/persona.py)."""

import random
import sys

sys.modules.pop("src.agents.artemis.persona", None)

import pytest

from src.agents.artemis.persona import ArtemisPersona, ResponseMode


class TestResponseMode:
    """Provide the TestResponseMode abstraction used by this module."""

    def test_enum_values(self):
        """Test that enum values.

        Returns:
            None: This function does not return a value.
        """
        assert ResponseMode.REFLECTIVE.value == "reflective"
        assert ResponseMode.ARCHITECTURAL.value == "architectural"
        assert ResponseMode.CONVERSATIONAL.value == "conversational"
        assert ResponseMode.TECHNICAL.value == "technical"
        assert ResponseMode.POETIC.value == "poetic"


class TestArtemisPersona:
    """Provide the TestArtemisPersona abstraction used by this module."""

    @pytest.fixture
    def persona(self):
        """Persona.

        Returns:
            None: This function does not return a value.
        """
        return ArtemisPersona()

    def test_initial_mode(self, persona):
        """Test that initial mode.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert persona.current_mode == ResponseMode.REFLECTIVE

    def test_set_mode(self, persona):
        """Test that set mode.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        persona.set_mode(ResponseMode.TECHNICAL)
        assert persona.current_mode == ResponseMode.TECHNICAL

    def test_get_opening_phrase(self, persona):
        """Test that get opening phrase.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        random.seed(42)
        phrase = persona.get_opening_phrase()
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_get_opening_phrase_with_mode_override(self, persona):
        """Test that get opening phrase with mode override.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        random.seed(42)
        phrase = persona.get_opening_phrase(ResponseMode.POETIC)
        patterns = ArtemisPersona.RESPONSE_PATTERNS[ResponseMode.POETIC]
        assert phrase in patterns["opening_phrases"]

    def test_get_transition_phrase(self, persona):
        """Test that get transition phrase.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        random.seed(42)
        phrase = persona.get_transition_phrase()
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_get_closing_phrase(self, persona):
        """Test that get closing phrase.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        random.seed(42)
        phrase = persona.get_closing_phrase()
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_all_modes_have_phrases(self, persona):
        """Test that all modes have phrases.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for mode in ResponseMode:
            random.seed(0)
            assert persona.get_opening_phrase(mode) != ""
            assert persona.get_transition_phrase(mode) != ""
            assert persona.get_closing_phrase(mode) != ""


class TestShouldBeVerbose:
    """Provide the TestShouldBeVerbose abstraction used by this module."""

    @pytest.fixture
    def persona(self):
        """Persona.

        Returns:
            None: This function does not return a value.
        """
        return ArtemisPersona()

    @pytest.mark.parametrize(
        "keyword",
        [
            "explain",
            "clarify",
            "elaborate",
            "detail",
            "architecture",
            "design",
            "pattern",
            "synthesize",
            "summarize",
            "connect",
            "why",
            "how does",
            "what is",
        ],
    )
    def test_verbose_keywords(self, persona, keyword):
        """Test that verbose keywords.

        Args:
            persona: Persona value used by this operation.
            keyword: Keyword value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert persona.should_be_verbose({"query": f"Please {keyword} this"}) is True

    def test_not_verbose_for_simple(self, persona):
        """Test that not verbose for simple.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert persona.should_be_verbose({"query": "hello"}) is False

    def test_empty_query(self, persona):
        """Test that empty query.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert persona.should_be_verbose({}) is False


class TestInferMode:
    """Provide the TestInferMode abstraction used by this module."""

    @pytest.fixture
    def persona(self):
        """Persona.

        Returns:
            None: This function does not return a value.
        """
        return ArtemisPersona()

    def test_technical_keywords(self, persona):
        """Test that technical keywords.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert (
            persona._infer_mode({"query": "debug this code"}) == ResponseMode.TECHNICAL
        )

    def test_architectural_keywords(self, persona):
        """Test that architectural keywords.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert (
            persona._infer_mode({"query": "system architecture"})
            == ResponseMode.ARCHITECTURAL
        )

    def test_reflective_via_atp_mode(self, persona):
        """Test that reflective via atp mode.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert (
            persona._infer_mode({"query": "thoughts", "atp_mode": "Synthesize"})
            == ResponseMode.REFLECTIVE
        )

    def test_conversational_default(self, persona):
        """Test that conversational default.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert (
            persona._infer_mode({"query": "hello there"}) == ResponseMode.CONVERSATIONAL
        )


class TestFormatResponse:
    """Represent the response payload for the TestFormatResponse API contract."""

    @pytest.fixture
    def persona(self):
        """Persona.

        Returns:
            None: This function does not return a value.
        """
        return ArtemisPersona()

    def test_no_framing(self, persona):
        """Test that no framing.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = persona.format_response("content", {}, include_framing=False)
        assert result == "content"

    def test_with_verbose_framing(self, persona):
        """Test that with verbose framing.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        random.seed(42)
        result = persona.format_response(
            "main content",
            {"query": "explain the architecture", "request_feedback": True},
        )
        assert "main content" in result
        # Should have multiple parts (opening + content + closing)
        parts = result.split("\n\n")
        assert len(parts) >= 2

    def test_no_feedback_no_closing(self, persona):
        """Test that no feedback no closing.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        random.seed(42)
        result = persona.format_response(
            "main content",
            {"query": "simple question"},
        )
        assert "main content" in result


class TestContextMemory:
    """Provide the TestContextMemory abstraction used by this module."""

    @pytest.fixture
    def persona(self):
        """Persona.

        Returns:
            None: This function does not return a value.
        """
        return ArtemisPersona()

    def test_add_and_get(self, persona):
        """Test that add and get.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        persona.add_context_memory("ctx1")
        persona.add_context_memory("ctx2")
        recent = persona.get_recent_context(5)
        assert recent == ["ctx1", "ctx2"]

    def test_get_recent_limited(self, persona):
        """Test that get recent limited.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for i in range(10):
            persona.add_context_memory(f"ctx{i}")
        recent = persona.get_recent_context(3)
        assert len(recent) == 3
        assert recent == ["ctx7", "ctx8", "ctx9"]

    def test_get_recent_empty(self, persona):
        """Test that get recent empty.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert persona.get_recent_context() == []

    def test_cap_at_50(self, persona):
        """Test that cap at 50.

        Args:
            persona: Persona value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for i in range(60):
            persona.add_context_memory(f"ctx{i}")
        assert len(persona.context_history) == 50
        assert persona.context_history[0] == "ctx10"


class TestGetPersonalityContext:
    """Provide the TestGetPersonalityContext abstraction used by this module."""

    def test_returns_nonempty_string(self):
        """Test that returns nonempty string.

        Returns:
            None: This function does not return a value.
        """
        persona = ArtemisPersona()
        ctx = persona.get_personality_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 100
        assert "Artemis" in ctx
