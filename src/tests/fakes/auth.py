"""Authentication test doubles that never persist transient proof."""

from __future__ import annotations

from dataclasses import dataclass

from src.auth.contracts import AuthReceiptV1
from src.auth.verifier import AuthenticationDenied, AuthenticationRequest


@dataclass(frozen=True)
class FakeAuthVerifier:
    """Return a configured receipt, or a stable denial, without retaining proof."""

    receipt: AuthReceiptV1 | None = None
    denial_code: str | None = None

    def verify(self, request: AuthenticationRequest) -> AuthReceiptV1:
        del request
        if self.denial_code is not None:
            raise AuthenticationDenied(self.denial_code)
        if self.receipt is None:
            raise AuthenticationDenied("authentication_rejected")
        return self.receipt
