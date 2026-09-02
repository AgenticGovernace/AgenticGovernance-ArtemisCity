"""atp.py — Artemis Transmission Protocol (ATP) build/parse + ack matching.

Implements the v0.3.1 transmission format described in ATP_PROTOCOL.md:
a fixed header (== envelope tags and # signal tags), a `---` separator, then
the payload. Includes the fault-awareness layer: unknown tags / mismatched ctx
do not get guessed at — the caller raises an intersect warning and halts.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

ATP_VERSION = "0.3.1"

# Symmetric tag contract: request -> set of valid replies.
SYMMETRIC = {
    "==handoff==": {"==accept==", "==decline=="},
    "==ask==": {"==rephrase==", "==decline=="},
    "==ref==": {"==ref_ack=="},
}

VALID_MODES = {"Build", "Review", "Organize", "Capture", "Synthesize", "Commit"}
VALID_ACTION_TYPES = {"Summarize", "Scaffold", "Execute", "Reflect"}
ACK_TAGS = {
    "==accept==",
    "==decline==",
    "==rephrase==",
    "==ref_ack==",
    "==intersect_warning==",
}

INTERSECT_WARNING = (
    "==intersect_warning== Tag not mapped in ATP. "
    "Request human arbitration or memory recall."
)


class ATPFault(Exception):
    """Raised when a transmission is malformed or carries an unmapped tag."""


def new_ctx() -> str:
    """Mint a fresh context hash, e.g. ctx_4df3a."""
    return "ctx_" + secrets.token_hex(3)


def reply_ctx_for(ctx: str) -> str:
    """The mirror context hash a reply must carry."""
    return "reply_" + ctx


@dataclass
class Transmission:
    """A Relay -> downstream-agent handoff."""

    to: str
    ctx: str
    mode: str
    context: str
    priority: str = "Normal"
    action_type: str = "Execute"
    target_zone: str = ""
    special_notes: str = ""
    request_tag: str = "==handoff=="
    expect: str = "==accept=="
    payload: str = ""
    sender: str = "Relay"

    def validate(self) -> None:
        if self.mode not in VALID_MODES:
            raise ATPFault(f"Invalid #Mode: {self.mode!r}")
        if self.action_type not in VALID_ACTION_TYPES:
            raise ATPFault(f"Invalid #ActionType: {self.action_type!r}")
        if self.request_tag not in SYMMETRIC:
            raise ATPFault(f"Unmapped request tag: {self.request_tag!r}")
        if self.expect not in SYMMETRIC[self.request_tag]:
            raise ATPFault(
                f"{self.expect!r} is not a valid reply to {self.request_tag!r}"
            )

    def render(self) -> str:
        self.validate()
        header = [
            f"==atp_version== {ATP_VERSION}",
            f"==from== {self.sender}",
            f"==to== {self.to}",
            f"==ctx== {self.ctx}",
            f"#Mode: {self.mode}",
            f"#Context: {self.context}",
            f"#Priority: {self.priority}",
            f"#ActionType: {self.action_type}",
            f"#TargetZone: {self.target_zone}",
        ]
        if self.special_notes:
            header.append(f"#SpecialNotes: {self.special_notes}")
        header.append(self.request_tag)
        header.append(f"==expect== {self.expect}")
        return "\n".join(header) + "\n---\n" + self.payload + "\n"


@dataclass
class Reply:
    """A parsed reply from a downstream agent."""

    sender: str = ""
    ctx: str = ""
    ack: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    payload: str = ""


def parse_reply(text: str) -> Reply:
    """Parse a downstream reply. Raises ATPFault on an unmapped/missing ack tag."""
    head, _, payload = text.partition("\n---\n")
    rep = Reply(payload=payload.strip())
    for raw in head.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("==from=="):
            rep.sender = (
                ln.split(None, 1)[1].strip() if len(ln.split(None, 1)) > 1 else ""
            )
        elif ln.startswith("==ctx=="):
            rep.ctx = ln.split(None, 1)[1].strip() if len(ln.split(None, 1)) > 1 else ""
        elif ln.startswith("#"):
            k, _, v = ln[1:].partition(":")
            rep.fields[k.strip()] = v.strip()
        elif ln in ACK_TAGS:
            rep.ack = ln
        elif (
            ln.startswith("==")
            and ln.endswith("==")
            and not ln.startswith("==atp_version==")
        ):
            # A == tag that is neither a known ack nor an envelope tag => unmapped.
            raise ATPFault(f"Unmapped ATP tag in reply: {ln!r}")
    if not rep.ack:
        raise ATPFault("Reply carries no recognized ack tag.")
    return rep


def match_ack(sent: Transmission, reply: Reply) -> str:
    """Validate that `reply` answers `sent`.

    Returns the ack tag on success. Raises ATPFault (fault-awareness layer) if the
    ctx does not mirror or the ack is not valid for the request.
    """
    if reply.ack == "==intersect_warning==":
        raise ATPFault("Downstream emitted ==intersect_warning==.")
    if reply.ctx != reply_ctx_for(sent.ctx):
        raise ATPFault(
            f"ctx mismatch: expected {reply_ctx_for(sent.ctx)!r}, got {reply.ctx!r}"
        )
    if reply.ack not in SYMMETRIC[sent.request_tag]:
        raise ATPFault(f"{reply.ack!r} is not a valid reply to {sent.request_tag!r}")
    return reply.ack
