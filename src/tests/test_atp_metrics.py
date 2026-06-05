"""Integration tests for ATP parser metrics."""

import sys
import time
from enum import Enum

import pytest

from src.agents.atp.atp_models import ATPMessage, ATPMode, ATPPriority
from src.agents.atp.atp_parser import ATPParser


def test_atp_parser_reimport_does_not_crash_on_duplicate_metrics():
    # Prometheus' default REGISTRY rejects duplicate names. Without the
    # safe_metric guard, sys.modules.pop + reimport raises ValueError.
    """Test that atp parser reimport does not crash on duplicate metrics.

    Returns:
        None: This function does not return a value.
    """
    sys.modules.pop("src.agents.atp.atp_parser", None)
    import src.agents.atp.atp_parser  # noqa: F401  (reimport must not raise)


def test_memory_bus_reimport_does_not_crash_on_duplicate_metrics():
    """Test that memory bus reimport does not crash on duplicate metrics.

    Returns:
        None: This function does not return a value.
    """
    sys.modules.pop("src.integration.memory_bus", None)
    import src.integration.memory_bus  # noqa: F401  (reimport must not raise)


class TestParseWithMetricsBasic:
    """Tests for parse_with_metrics return structure."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_returns_tuple(self, parser):
        """parse_with_metrics returns a (ATPMessage, dict) tuple.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = parser.parse_with_metrics("#Mode: Build\n#Context: test")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_atp_message(self, parser):
        """First element of the tuple is an ATPMessage.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        message, _ = parser.parse_with_metrics("#Mode: Build")
        assert isinstance(message, ATPMessage)

    def test_second_element_is_dict(self, parser):
        """Second element of the tuple is a metrics dict.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("#Mode: Build")
        assert isinstance(metrics, dict)

    def test_metrics_has_required_keys(self, parser):
        """Metrics dict has all expected keys.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("#Mode: Build\n#Context: test")
        expected_keys = {
            "parse_latency_ms",
            "format_detected",
            "has_headers",
            "is_complete",
            "fields_populated",
            "field_count",
            "content_length",
            "raw_length",
        }
        assert expected_keys.issubset(set(metrics.keys()))


class TestLatencyTracking:
    """Tests for latency instrumentation."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_latency_non_negative(self, parser):
        """Parse latency is a non-negative float.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("#Mode: Build")
        assert metrics["parse_latency_ms"] >= 0

    def test_latency_consistency(self, parser):
        """Similar inputs produce latencies in the same order of magnitude.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, m1 = parser.parse_with_metrics("#Mode: Build\n#Context: A")
        _, m2 = parser.parse_with_metrics("#Mode: Review\n#Context: B")
        ratio = m1["parse_latency_ms"] / max(m2["parse_latency_ms"], 0.001)
        assert 0.01 < ratio < 100

    def test_throughput(self, parser):
        """Parser can handle multiple invocations quickly.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        start = time.time()
        for _ in range(50):
            parser.parse_with_metrics("#Mode: Build")
        elapsed = time.time() - start
        assert elapsed < 5.0  # 50 parses in under 5 seconds


class TestFormatDetection:
    """Tests for format_detected metric."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_hash_format_detected(self, parser):
        """Hash format (#Tag:) is correctly detected.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("#Mode: Build\n#Context: test")
        assert metrics["format_detected"] == "hash"

    def test_bracket_format_detected(self, parser):
        """Bracket format ([[Tag]]:) is correctly detected.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("[[Mode]]: Build\n[[Context]]: test")
        assert metrics["format_detected"] == "bracket"

    def test_no_format_detected(self, parser):
        """Plain text returns None for format_detected.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("just some plain text")
        assert metrics["format_detected"] is None

    def test_has_headers_true(self, parser):
        """has_headers is True when ATP headers are present.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("#Mode: Build\n#Context: test")
        assert metrics["has_headers"] is True

    def test_has_headers_false(self, parser):
        """has_headers is False for plain text.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("no headers here")
        assert metrics["has_headers"] is False


class TestFieldCounting:
    """Tests for field counting metrics."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_field_count_with_multiple_headers(self, parser):
        """field_count reflects number of populated ATP fields.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        atp = "#Mode: Build\n#Context: test\n#Priority: High"
        _, metrics = parser.parse_with_metrics(atp)
        assert metrics["field_count"] >= 2  # mode + context at minimum

    def test_fields_populated_list(self, parser):
        """fields_populated is a list of field names.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        atp = "#Mode: Build\n#Context: testing\n#Priority: High"
        _, metrics = parser.parse_with_metrics(atp)
        assert isinstance(metrics["fields_populated"], list)
        assert "mode" in metrics["fields_populated"]
        assert "context" in metrics["fields_populated"]

    def test_field_count_zero_for_plain_text(self, parser):
        """field_count is 0 when no ATP headers are present.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("plain text without headers")
        assert metrics["field_count"] == 0

    def test_field_count_matches_populated_length(self, parser):
        """field_count equals len(fields_populated).

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        atp = "#Mode: Build\n#Context: test"
        _, metrics = parser.parse_with_metrics(atp)
        assert metrics["field_count"] == len(metrics["fields_populated"])


class TestContentMetrics:
    """Tests for content_length and raw_length metrics."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_raw_length(self, parser):
        """raw_length matches the input string length.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        atp = "#Mode: Build"
        _, metrics = parser.parse_with_metrics(atp)
        assert metrics["raw_length"] == len(atp)

    def test_content_length_non_negative(self, parser):
        """content_length is non-negative.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("#Mode: Build\nSome content here")
        assert metrics["content_length"] >= 0

    def test_empty_input(self, parser):
        """Empty string still produces valid metrics.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, metrics = parser.parse_with_metrics("")
        assert metrics["raw_length"] == 0
        assert metrics["parse_latency_ms"] >= 0
        assert metrics["field_count"] == 0


class TestMessageParsing:
    """Tests for the parsed ATPMessage returned alongside metrics."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_mode_parsed(self, parser):
        """Mode header is correctly parsed into the message.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        message, _ = parser.parse_with_metrics("#Mode: Build")
        assert message.mode == ATPMode.BUILD

    def test_context_parsed(self, parser):
        """Context header is captured in the message.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        message, _ = parser.parse_with_metrics("#Mode: Build\n#Context: My context")
        assert message.context is not None
        assert "My context" in message.context

    def test_priority_parsed(self, parser):
        """Priority header is parsed into the message.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        message, _ = parser.parse_with_metrics("#Priority: High")
        assert message.priority == ATPPriority.HIGH

    def test_plain_text_content(self, parser):
        """Plain text is stored as content with no headers.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        message, _ = parser.parse_with_metrics("Just plain text")
        assert message.content == "Just plain text"

    def test_metrics_stored_in_metadata(self, parser):
        """Metrics are also stored in message.metadata['parse_metrics'].

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        message, metrics = parser.parse_with_metrics("#Mode: Build")
        assert "parse_metrics" in message.metadata
        assert message.metadata["parse_metrics"] == metrics

    def test_complex_input(self, parser):
        """Complex ATP input with all fields parses correctly.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        atp = (
            "#Mode: Build\n"
            "#Context: Full integration test\n"
            "#Priority: Critical\n"
            "#ActionType: Execute\n"
            "#TargetZone: /projects/test\n"
            "#SpecialNotes: Handle with care\n"
            "---\n"
            "The actual body content here."
        )
        message, metrics = parser.parse_with_metrics(atp)
        assert metrics["has_headers"] is True
        assert metrics["field_count"] >= 4
        assert message.mode == ATPMode.BUILD

    def test_multiple_parses_independent(self, parser):
        """Multiple calls return independent results.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        _, m1 = parser.parse_with_metrics("#Mode: Build")
        _, m2 = parser.parse_with_metrics("plain text")
        assert m1["has_headers"] is True
        assert m2["has_headers"] is False


class TestParserEdgeCases:
    """Additional branch coverage for parser helper paths."""

    @pytest.fixture
    def parser(self):
        """Parser.

        Returns:
            None: This function does not return a value.
        """
        return ATPParser()

    def test_is_atp_formatted_helper(self, parser):
        """is_atp_formatted mirrors detect_format behavior.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert parser.is_atp_formatted("#Mode: Build") is True
        assert parser.is_atp_formatted("plain text") is False

    def test_parse_enum_name_fallback_and_default(self, parser):
        """_parse_enum handles name lookup and default fallback.

        Args:
            parser: Parser value used by this operation.

        Returns:
            None: This function does not return a value.
        """

        class _Dummy(Enum):
            RED = "r"
            BLUE = "b"

        assert parser._parse_enum("RED", _Dummy, _Dummy.BLUE) == _Dummy.RED
        assert parser._parse_enum("unknown", _Dummy, _Dummy.BLUE) == _Dummy.BLUE

    def test_parse_with_metrics_re_raises_parse_errors(self, parser, monkeypatch):
        """Errors in parse() are surfaced to callers.

        Args:
            parser: Parser value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        monkeypatch.setattr(
            parser, "parse", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError, match="boom"):
            parser.parse_with_metrics("anything")
