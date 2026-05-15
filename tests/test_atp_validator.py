"""Tests for the ATP validator (src/agents/atp/atp_validator.py)."""

import sys

sys.modules.pop("agents.atp.atp_validator", None)

import pytest
from agents.atp.atp_models import ATPActionType, ATPMessage, ATPMode, ATPPriority
from agents.atp.atp_validator import ATPValidator, ValidationResult


# ---------------------------------------------------------------------------
# Helper to build ATPMessage with desired property values
# ---------------------------------------------------------------------------
def _msg(
    mode=ATPMode.UNKNOWN,
    context=None,
    action_type=ATPActionType.UNKNOWN,
    content="",
    target_zone=None,
    special_notes=None,
):
    return ATPMessage(
        mode=mode,
        context=context,
        action_type=action_type,
        content=content,
        target_zone=target_zone,
        special_notes=special_notes,
    )


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------
class TestValidationResult:
    def test_initial_state(self):
        r = ValidationResult()
        assert r.is_valid is True
        assert r.warnings == []
        assert r.errors == []
        assert r.suggestions == []
        assert r.has_issues is False

    def test_add_warning(self):
        r = ValidationResult()
        r.add_warning("heads up")
        assert r.warnings == ["heads up"]
        assert r.is_valid is True
        assert r.has_issues is True

    def test_add_error(self):
        r = ValidationResult()
        r.add_error("bad")
        assert r.errors == ["bad"]
        assert r.is_valid is False
        assert r.has_issues is True

    def test_add_suggestion(self):
        r = ValidationResult()
        r.add_suggestion("try this")
        assert r.suggestions == ["try this"]
        assert r.is_valid is True
        assert r.has_issues is False

    def test_str_no_issues(self):
        r = ValidationResult()
        assert "no issues" in str(r).lower()

    def test_str_with_all(self):
        r = ValidationResult()
        r.add_error("err1")
        r.add_warning("warn1")
        r.add_suggestion("sug1")
        output = str(r)
        assert "Errors (1)" in output
        assert "err1" in output
        assert "Warnings (1)" in output
        assert "warn1" in output
        assert "Suggestions (1)" in output
        assert "sug1" in output


# ---------------------------------------------------------------------------
# ATPValidator – lenient mode (default)
# ---------------------------------------------------------------------------
class TestATPValidatorLenient:
    @pytest.fixture
    def validator(self):
        return ATPValidator(strict=False)

    def test_valid_complete_message(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="building a feature",
            action_type=ATPActionType.SCAFFOLD,
            content="Create the scaffold for new module",
        )
        assert msg.has_atp_headers is True
        assert msg.is_complete is True
        result = validator.validate(msg)
        assert result.is_valid is True
        assert result.errors == []

    def test_no_headers_gives_suggestion(self, validator):
        msg = _msg(content="plain text message here")
        assert msg.has_atp_headers is False
        result = validator.validate(msg)
        assert result.is_valid is True
        assert len(result.suggestions) >= 1
        assert any("ATP headers" in s for s in result.suggestions)

    def test_incomplete_headers_gives_warning(self, validator):
        # has context (so has_atp_headers=True) but mode+action are UNKNOWN (not complete)
        msg = _msg(context="some ctx", content="enough content for validation")
        assert msg.has_atp_headers is True
        assert msg.is_complete is False
        result = validator.validate(msg)
        assert result.is_valid is True
        assert any("missing" in w.lower() for w in result.warnings)

    def test_empty_content_is_error(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.EXECUTE,
            content="",
        )
        result = validator.validate(msg)
        assert result.is_valid is False
        assert any("empty" in e.lower() for e in result.errors)

    def test_short_content_warning(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.EXECUTE,
            content="short",
        )
        result = validator.validate(msg)
        assert any("short" in w.lower() for w in result.warnings)

    def test_long_content_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.EXECUTE,
            content="x" * 2500,
        )
        result = validator.validate(msg)
        assert any(
            "breaking" in s.lower() or "long" in s.lower() for s in result.suggestions
        )


# ---------------------------------------------------------------------------
# ATPValidator – strict mode
# ---------------------------------------------------------------------------
class TestATPValidatorStrict:
    @pytest.fixture
    def validator(self):
        return ATPValidator(strict=True)

    def test_no_headers_is_error(self, validator):
        msg = _msg(content="plain text message here")
        result = validator.validate(msg)
        assert result.is_valid is False
        assert any("header" in e.lower() for e in result.errors)

    def test_incomplete_headers_is_error(self, validator):
        msg = _msg(context="some ctx", content="enough content for validation")
        result = validator.validate(msg)
        assert result.is_valid is False
        assert any("incomplete" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Mode/action consistency
# ---------------------------------------------------------------------------
class TestModeActionConsistency:
    @pytest.fixture
    def validator(self):
        return ATPValidator()

    def test_consistent_pair_no_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.SCAFFOLD,
            content="enough content for validation",
        )
        result = validator.validate(msg)
        assert not any("typically uses" in s for s in result.suggestions)

    def test_inconsistent_pair_gives_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.REFLECT,
            content="enough content for validation",
        )
        result = validator.validate(msg)
        assert any("typically uses" in s for s in result.suggestions)

    def test_unknown_action_no_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.UNKNOWN,
            content="enough content for validation",
        )
        result = validator.validate(msg)
        assert not any("typically uses" in s for s in result.suggestions)


# ---------------------------------------------------------------------------
# Target zone validation
# ---------------------------------------------------------------------------
class TestTargetZoneValidation:
    @pytest.fixture
    def validator(self):
        return ATPValidator()

    def test_absolute_path_no_extra_suggestions(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.SCAFFOLD,
            content="enough content for validation",
            target_zone="/home/user/project",
        )
        result = validator.validate(msg)
        assert not any("absolute" in s.lower() for s in result.suggestions)

    def test_relative_path_gives_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.SCAFFOLD,
            content="enough content for validation",
            target_zone="src/agents",
        )
        result = validator.validate(msg)
        assert any("absolute" in s.lower() for s in result.suggestions)

    def test_no_path_separators_gives_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.SCAFFOLD,
            content="enough content for validation",
            target_zone="myproject",
        )
        result = validator.validate(msg)
        assert any("file path" in s.lower() for s in result.suggestions)


# ---------------------------------------------------------------------------
# suggest_improvements
# ---------------------------------------------------------------------------
class TestSuggestImprovements:
    @pytest.fixture
    def validator(self):
        return ATPValidator()

    def test_no_headers_suggests_adding(self, validator):
        msg = _msg(content="plain text")
        suggestions = validator.suggest_improvements(msg)
        assert any("ATP headers" in s for s in suggestions)

    def test_missing_target_zone(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD, context="ctx", action_type=ATPActionType.SCAFFOLD
        )
        suggestions = validator.suggest_improvements(msg)
        assert any("TargetZone" in s for s in suggestions)

    def test_missing_special_notes(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="ctx",
            action_type=ATPActionType.SCAFFOLD,
            target_zone="/project",
        )
        suggestions = validator.suggest_improvements(msg)
        assert any("SpecialNotes" in s for s in suggestions)

    def test_short_context_suggestion(self, validator):
        msg = _msg(mode=ATPMode.BUILD, context="hi", action_type=ATPActionType.SCAFFOLD)
        suggestions = validator.suggest_improvements(msg)
        assert any("descriptive" in s.lower() for s in suggestions)

    def test_adequate_context_no_suggestion(self, validator):
        msg = _msg(
            mode=ATPMode.BUILD,
            context="Building a new agent module for research tasks",
            action_type=ATPActionType.SCAFFOLD,
            target_zone="/project",
            special_notes="none",
        )
        suggestions = validator.suggest_improvements(msg)
        assert suggestions == []
