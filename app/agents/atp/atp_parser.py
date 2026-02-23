"""ATP (Artemis Transmission Protocol) parser.

This module parses ATP-formatted messages from user input, supporting both
#Tag: and [[Tag]]: syntax formats for protocol headers.

Enhanced with parse-time metrics for observability and kernel routing.
"""

import re
import time
from typing import Dict, Optional, Tuple

from .atp_models import ATPActionType, ATPMessage, ATPMode, ATPPriority

# Optional Prometheus metrics
try:
    from prometheus_client import Counter, Histogram

    _METRICS_ENABLED = True
except ImportError:
    _METRICS_ENABLED = False
    Counter = Histogram = None

if _METRICS_ENABLED:
    ATP_PARSE_LATENCY = Histogram(
        "artemis_atp_parse_latency_ms",
        "ATP message parse latency in milliseconds",
        buckets=[0.1, 0.5, 1, 2, 5, 10, 50],
    )
    ATP_PARSE_TOTAL = Counter(
        "artemis_atp_parse_total",
        "Total ATP messages parsed",
        ["format", "has_headers"],
    )
    ATP_PARSE_ERRORS = Counter(
        "artemis_atp_parse_errors_total",
        "ATP parse errors",
    )


class ATPParser:
    """Parser for ATP-formatted messages.

    Supports two syntax formats:
    1. Hash format: #Mode: Build, #Context: description
    2. Bracket format: [[Mode]]: Build, [[Context]]: description
    """

    # Regex patterns for both ATP formats
    HASH_PATTERN = r'#(\w+):\s*(.+?)(?=\s*#\w+:|$)'
    BRACKET_PATTERN = r'\[\[(\w+)\]\]:\s*(.+?)(?=\s*\[\[\w+\]\]:|$)'

    # Known ATP tags
    ATP_TAGS = {'mode', 'context', 'priority', 'actiontype', 'targetzone', 'specialnotes'}

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

    def _extract_headers(self, text: str, pattern: re.Pattern) -> Tuple[dict, str]:
        """Extract ATP headers and remaining content.

        Args:
            text: Text to parse
            pattern: Compiled regex pattern for header format

        Returns:
            Tuple of (headers dict, remaining content)
        """
        headers = {}
        matches = pattern.findall(text)

        if not matches:
            return headers, text

        # Extract headers
        for tag, value in matches:
            tag_lower = tag.lower().replace('_', '')
            if tag_lower in self.ATP_TAGS:
                headers[tag_lower] = value.strip()

        # Remove headers from content
        content = pattern.sub('', text)

        # Clean up separator lines (---)
        content = re.sub(r'\n\s*-{3,}\s*\n', '\n\n', content)

        return headers, content

    def _populate_message_fields(self, message: ATPMessage, headers: dict) -> None:
        """Populate ATP message fields from parsed headers.

        Args:
            message: ATPMessage to populate
            headers: Dictionary of parsed headers
        """
        # Mode
        if 'mode' in headers:
            message.mode = self._parse_enum(headers['mode'], ATPMode, ATPMode.UNKNOWN)

        # Context
        if 'context' in headers:
            message.context = headers['context']

        # Priority
        if 'priority' in headers:
            message.priority = self._parse_enum(
                headers['priority'], ATPPriority, ATPPriority.NORMAL
            )

        # Action Type
        if 'actiontype' in headers:
            message.action_type = self._parse_enum(
                headers['actiontype'], ATPActionType, ATPActionType.UNKNOWN
            )

        # Target Zone
        if 'targetzone' in headers:
            message.target_zone = headers['targetzone']

        # Special Notes
        if 'specialnotes' in headers:
            message.special_notes = headers['specialnotes']

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

    def detect_format(self, text: str) -> Optional[str]:
        """Detect which ATP format is used in text.

        Args:
            text: Text to analyze

        Returns:
            'hash' for #Tag: format, 'bracket' for [[Tag]]: format, None if neither
        """
        if self.hash_regex.search(text):
            return 'hash'
        elif self.bracket_regex.search(text):
            return 'bracket'
        return None

    def is_atp_formatted(self, text: str) -> bool:
        """Check if text contains ATP headers.

        Args:
            text: Text to check

        Returns:
            True if ATP headers detected
        """
        return self.detect_format(text) is not None

    def parse_with_metrics(self, raw_input: str) -> Tuple[ATPMessage, Dict]:
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

            # Emit Prometheus metrics if available
            if _METRICS_ENABLED:
                ATP_PARSE_LATENCY.observe(parse_latency_ms)
                ATP_PARSE_TOTAL.labels(
                    format=format_detected or "none",
                    has_headers=str(has_headers).lower(),
                ).inc()

            # Store metrics in message metadata
            message.metadata["parse_metrics"] = metrics

            return message, metrics

        except Exception as e:
            if _METRICS_ENABLED:
                ATP_PARSE_ERRORS.inc()
            raise
