"""Compatibility wrapper for ``memory.integration.trust_interface``.

Canonical implementation lives in ``src.integration.trust_interface``.
"""

from src.integration.trust_interface import (TRUST_THRESHOLDS, TrustInterface,
                                             TrustLevel, TrustScore,
                                             get_trust_interface,
                                             reset_trust_interface_for_tests)

__all__ = [
    "TRUST_THRESHOLDS",
    "TrustInterface",
    "TrustLevel",
    "TrustScore",
    "get_trust_interface",
    "reset_trust_interface_for_tests",
]
