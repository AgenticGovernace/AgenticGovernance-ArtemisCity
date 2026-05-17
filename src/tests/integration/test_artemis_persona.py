"""Tests for the Artemis persona (src/agents/artemis/persona.py)."""

import sys
import random

sys.modules.pop("agents.artemis.persona", None)

import pytest
from agents.artemis.persona import ArtemisPersona, ResponseMode


class TestResponseMode:
    def test_enum_values(self):
        assert ResponseMode.REFLECTIVE.value == "reflective"
        assert ResponseMode.ARCHITECTURAL.value == "architectural"
        assert ResponseMode.CONVERSATIONAL.value == "conversational"
        assert ResponseMode.TECHNICAL.value == "technical"
        assert ResponseMode.POETIC.value == "poetic"


class TestArtemisPersona:
    @pytest.fixture
    def persona(self):
        return ArtemisPersona()

    def test_initial_mode(self, persona):
        assert persona.current_mode == ResponseMode.REFLECTIVE

    def test_set_mode(self, persona):
        persona.set_mode(ResponseMode.TECHNICAL)
        assert persona.current_mode == ResponseMode.TECHNICAL

    def test_get_opening_phrase(self, persona):
        random.seed(42)
        phrase = persona.get_opening_phrase()
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_get_opening_phrase_with_mode_override(self, persona):
        random.seed(42)
        phrase = persona.get_opening_phrase(ResponseMode.POETIC)
        patterns = ArtemisPersona.RESPONSE_PATTERNS[ResponseMode.POETIC]
        assert phrase in patterns["opening_phrases"]

    def test_get_transition_phrase(self, persona):
        random.seed(42)
        phrase = persona.get_transition_phrase()
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_get_closing_phrase(self, persona):
        random.seed(42)
        phrase = persona.get_closing_phrase()
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_all_modes_have_phrases(self, persona):
        for mode in ResponseMode:
            random.seed(0)
            assert persona.get_opening_phrase(mode) != ""
            assert persona.get_transition_phrase(mode) != ""
            assert persona.get_closing_phrase(mode) != ""


class TestShouldBeVerbose:
    @pytest.fixture
    def persona(self):
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
        assert persona.should_be_verbose({"query": f"Please {keyword} this"}) is True

    def test_not_verbose_for_simple(self, persona):
        assert persona.should_be_verbose({"query": "hello"}) is False

    def test_empty_query(self, persona):
        assert persona.should_be_verbose({}) is False


class TestInferMode:
    @pytest.fixture
    def persona(self):
        return ArtemisPersona()

    def test_technical_keywords(self, persona):
        assert (
            persona._infer_mode({"query": "debug this code"}) == ResponseMode.TECHNICAL
        )

    def test_architectural_keywords(self, persona):
        assert (
            persona._infer_mode({"query": "system architecture"})
            == ResponseMode.ARCHITECTURAL
        )

    def test_reflective_via_atp_mode(self, persona):
        assert (
            persona._infer_mode({"query": "thoughts", "atp_mode": "Synthesize"})
            == ResponseMode.REFLECTIVE
        )

    def test_conversational_default(self, persona):
        assert (
            persona._infer_mode({"query": "hello there"}) == ResponseMode.CONVERSATIONAL
        )


class TestFormatResponse:
    @pytest.fixture
    def persona(self):
        return ArtemisPersona()

    def test_no_framing(self, persona):
        result = persona.format_response("content", {}, include_framing=False)
        assert result == "content"

    def test_with_verbose_framing(self, persona):
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
        random.seed(42)
        result = persona.format_response(
            "main content",
            {"query": "simple question"},
        )
        assert "main content" in result


class TestContextMemory:
    @pytest.fixture
    def persona(self):
        return ArtemisPersona()

    def test_add_and_get(self, persona):
        persona.add_context_memory("ctx1")
        persona.add_context_memory("ctx2")
        recent = persona.get_recent_context(5)
        assert recent == ["ctx1", "ctx2"]

    def test_get_recent_limited(self, persona):
        for i in range(10):
            persona.add_context_memory(f"ctx{i}")
        recent = persona.get_recent_context(3)
        assert len(recent) == 3
        assert recent == ["ctx7", "ctx8", "ctx9"]

    def test_get_recent_empty(self, persona):
        assert persona.get_recent_context() == []

    def test_cap_at_50(self, persona):
        for i in range(60):
            persona.add_context_memory(f"ctx{i}")
        assert len(persona.context_history) == 50
        assert persona.context_history[0] == "ctx10"


class TestGetPersonalityContext:
    def test_returns_nonempty_string(self):
        persona = ArtemisPersona()
        ctx = persona.get_personality_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 100
        assert "Artemis" in ctx
