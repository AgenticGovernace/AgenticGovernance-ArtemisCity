"""ATP (Artemis Transmission Protocol) parser.

This module parses ATP-formatted messages from user input, supporting both
#Tag: and [[Tag]]: syntax formats for protocol headers.

Enhanced with parse-time metrics for observability and kernel routing.
"""

#  Copyright (c) 2026. Lorem ipsum dolor sit amet, consectetur adipiscing elit.
#  Morbi non lorem porttitor neque feugiat blandit. Ut vitae ipsum eget quam lacinia accumsan.
#  Etiam sed turpis ac ipsum condimentum fringilla. Maecenas magna.
#  Proin dapibus sapien vel ante. Aliquam erat volutpat. Pellentesque sagittis ligula eget metus.
#  Vestibulum commodo. Ut rhoncus gravida arcu.

import re
import time
from typing import Any, ClassVar

from .atp_models import ATPActionType, ATPMessage, ATPMode, ATPPriority

_PARSE_METRICS: tuple[Any, Any, Any] | None = None
ATP_PARSE_LATENCY: Any
ATP_PARSE_TOTAL: Any
ATP_PARSE_ERRORS: Any


def _get_parse_metrics() -> tuple[Any, Any, Any]:
    """Create parser metrics only for instrumented parsing."""
    global _PARSE_METRICS, ATP_PARSE_ERRORS, ATP_PARSE_LATENCY, ATP_PARSE_TOTAL

    if _PARSE_METRICS is None:
        from prometheus_client import Counter, Histogram

        from src.utils.prometheus_guard import safe_metric

        _PARSE_METRICS = (
            safe_metric(
                Histogram,
                "artemis_atp_parse_latency_ms",
                "ATP message parse latency in milliseconds",
                buckets=[0.1, 0.5, 1, 2, 5, 10, 50],
            ),
            safe_metric(
                Counter,
                "artemis_atp_parse_total",
                "Total ATP messages parsed",
                ["format", "has_headers"],
            ),
            safe_metric(
                Counter,
                "artemis_atp_parse_errors_total",
                "ATP parse errors",
            ),
        )
        ATP_PARSE_LATENCY, ATP_PARSE_TOTAL, ATP_PARSE_ERRORS = _PARSE_METRICS
    return _PARSE_METRICS


def __getattr__(name: str) -> Any:
    """Resolve legacy metric exports without creating them at module import."""
    if name not in {"ATP_PARSE_LATENCY", "ATP_PARSE_TOTAL", "ATP_PARSE_ERRORS"}:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    _get_parse_metrics()
    return globals()[name]


class ATPParser:
    """Parser for ATP-formatted messages.

    Supports two syntax formats:
    1. Hash format: #Mode: Build, #Context: description
    2. Bracket format: [[Mode]]: Build, [[Context]]: description
    """

    # Regex patterns for both ATP formats
    HASH_PATTERN = r"#(\w+):\s*(.+?)(?=\s*#\w+:|$)"
    BRACKET_PATTERN = r"\[\[(\w+)\]\]:\s*(.+?)(?=\s*\[\[\w+\]\]:|$)"

    # Known ATP tags
    ATP_TAGS: ClassVar[set[str]] = {
        "mode",
        "context",
        "priority",
        "action",
        "actiontype",
        "targetzone",
        "specialnotes",
    }

    def __init__(self):
        """Initialize ATP parser."""
        self.hash_regex = re.compile(self.HASH_PATTERN, re.MULTILINE | re.DOTALL)
        self.bracket_regex = re.compile(self.BRACKET_PATTERN, re.MULTILINE | re.DOTALL)

    def parse(self, raw_input: str) -> ATPMessage:
        """Parse raw input into ATP message.

        Args:
            raw_input: Raw user input potentially containing ATP headers

        Returns:
            ATPMessage: Parsed message with extracted headers and content
        """
        message = ATPMessage(raw_input=raw_input)

        # Try hash format first
        headers, content = self._extract_headers(raw_input, self.hash_regex)

        # If no hash headers found, try bracket format
        if not headers:
            headers, content = self._extract_headers(raw_input, self.bracket_regex)

        # If still no headers, treat entire input as content
        if not headers:
            message.content = raw_input.strip()
            return message

        # Populate message fields from headers
        message.content = content.strip()
        self._populate_message_fields(message, headers)

        return message

    def _extract_headers(
        self, text: str, pattern: re.Pattern[str]
    ) -> tuple[dict[str, str], str]:
        """Extract ATP headers and remaining content.

        Args:
            text: Text to parse
            pattern: Compiled regex pattern for header format

        Returns:
            Tuple of (headers dict, remaining content)
        """
        headers: dict[str, str] = {}
        matches = pattern.findall(text)

        if not matches:
            return headers, text

        # Extract headers
        for tag, value in matches:
            tag_lower = tag.lower().replace("_", "")
            if tag_lower in self.ATP_TAGS:
                headers[tag_lower] = value.strip()

        # Remove headers from content
        content = pattern.sub("", text)

        # Clean up separator lines (---) securely
        content = re.sub(r"\n *-{3,} *\n", "\n\n", content)

        return headers, content

    def _populate_message_fields(self, message: ATPMessage, headers: dict) -> None:
        """Populate ATP message fields from parsed headers.

        Args:
            message: ATPMessage to populate
            headers: Dictionary of parsed headers
        """
        # Mode
        if "mode" in headers:
            message.mode = self._parse_enum(headers["mode"], ATPMode, ATPMode.UNKNOWN)

        # Context
        if "context" in headers:
            message.context = headers["context"]

        # Priority
        if "priority" in headers:
            message.priority = self._parse_enum(
                headers["priority"], ATPPriority, ATPPriority.NORMAL
            )

        # Action Type
        action_value = headers.get("actiontype") or headers.get("action")
        if action_value is not None:
            message.action_type = self._parse_enum(
                action_value, ATPActionType, ATPActionType.UNKNOWN
            )

        # Target Zone
        if "targetzone" in headers:
            message.target_zone = headers["targetzone"]

        # Special Notes
        if "specialnotes" in headers:
            message.special_notes = headers["specialnotes"]

    @staticmethod
    def _parse_enum(value: str, enum_class, default):
        """Parse string value to enum, returning default if not found.

        Args:
            value: String value to parse
            enum_class: Enum class to parse into
            default: Default value if parsing fails

        Returns:
            Enum member or default
        """
        # Try exact match first
        for member in enum_class:
            if member.value.lower() == value.lower():
                return member

        # Try name match
        try:
            return enum_class[value.upper()]
        except KeyError:
            return default

    def detect_format(self, text: str) -> str | None:
        """Detect which ATP format is used in text.

        Args:
            text: Text to analyze

        Returns:
            'hash' for #Tag: format, 'bracket' for [[Tag]]: format, None if neither
        """
        if self.hash_regex.search(text):
            return "hash"
        elif self.bracket_regex.search(text):
            return "bracket"
        return None

    def is_atp_formatted(self, text: str) -> bool:
        """Check if text contains ATP headers.

        Args:
            text: Text to check

        Returns:
            True if ATP headers detected
        """
        return self.detect_format(text) is not None

    def parse_with_metrics(self, raw_input: str) -> tuple[ATPMessage, dict[str, Any]]:
        """Parse ATP message and return both the message and parse metrics.

        Wraps the standard parse() call with timing instrumentation for
        kernel routing and observability dashboards.

        Args:
            raw_input: Raw user input potentially containing ATP headers

        Returns:
            Tuple of (ATPMessage, metrics_dict) where metrics_dict contains:
                - parse_latency_ms: Time to parse in milliseconds
                - format_detected: 'hash', 'bracket', or None
                - has_headers: Whether ATP headers were found
                - fields_populated: List of populated ATP fields
        """
        parse_latency, parse_total, parse_errors = _get_parse_metrics()
        start_time = time.perf_counter()

        try:
            message = self.parse(raw_input)
            parse_latency_ms = (time.perf_counter() - start_time) * 1000

            format_detected = self.detect_format(raw_input)
            has_headers = message.has_atp_headers

            # Track which fields were populated
            fields_populated = []
            if message.mode != ATPMode.UNKNOWN:
                fields_populated.append("mode")
            if message.context is not None:
                fields_populated.append("context")
            if message.priority != ATPPriority.NORMAL:
                fields_populated.append("priority")
            if message.action_type != ATPActionType.UNKNOWN:
                fields_populated.append("action_type")
            if message.target_zone is not None:
                fields_populated.append("target_zone")
            if message.special_notes is not None:
                fields_populated.append("special_notes")

            metrics = {
                "parse_latency_ms": parse_latency_ms,
                "format_detected": format_detected,
                "has_headers": has_headers,
                "is_complete": message.is_complete,
                "fields_populated": fields_populated,
                "field_count": len(fields_populated),
                "content_length": len(message.content),
                "raw_length": len(raw_input),
            }

            parse_latency.observe(parse_latency_ms)
            parse_total.labels(
                format=format_detected or "none",
                has_headers=str(has_headers).lower(),
            ).inc()

            # Store metrics in message metadata
            message.metadata["parse_metrics"] = metrics

            return message, metrics

        except Exception:
            parse_errors.inc()
            raise
