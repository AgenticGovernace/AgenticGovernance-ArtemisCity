"""memory.py — Relay's persistent reflection store, backed by Notion.

Relay's long-term memory is a Notion page ("Relay — Reflections"). It is the
CANONICAL store and survives across sessions:

  * on session start, `load_reflections()` reads the page back into context;
  * after every major action, `add_reflection()` appends a dated block.

If Notion is unreachable we fall back to `reflections/local-mirror.md` and flag a
`notion_unreachable` fault so the dispatcher can reconcile on the next session.
Notion wins on conflict.

The Notion calls are isolated in `_NotionClient`. This reference uses the public
Notion API shape (append block children / fetch block children) but is written so
the HTTP layer can be swapped for an MCP Notion connector without touching the
dispatcher. If the `requests` library or a token is absent, the client reports
itself unavailable and Relay uses the mirror.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

try:  # optional dependency; absence just forces the local-mirror fallback
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Reflection:
    text: str
    ctx: Optional[str]
    session_id: str
    ts: str

    def as_line(self) -> str:
        ctx = f" [{self.ctx}]" if self.ctx else ""
        return f"- {self.ts} ({self.session_id}){ctx}: {self.text}"


class _NotionClient:
    """Thin Notion wrapper. Swap the HTTP body for an MCP connector if preferred."""

    def __init__(self, page_id: str, token: Optional[str]):
        self.page_id = page_id
        self.token = token

    @property
    def available(self) -> bool:
        return bool(
            requests
            and self.token
            and self.page_id
            and self.page_id != "REPLACE_WITH_NOTION_PAGE_ID"
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def append(self, reflection: Reflection) -> None:
        body = {
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"type": "text", "text": {"content": reflection.as_line()}}
                        ]
                    },
                }
            ]
        }
        resp = requests.patch(  # type: ignore[union-attr]
            f"{NOTION_API}/blocks/{self.page_id}/children",
            headers=self._headers(),
            json=body,
            timeout=20,
        )
        resp.raise_for_status()

    def read_all(self) -> List[str]:
        out: List[str] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = requests.get(  # type: ignore[union-attr]
                f"{NOTION_API}/blocks/{self.page_id}/children",
                headers=self._headers(),
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for block in data.get("results", []):
                rich = block.get(block.get("type", ""), {}).get("rich_text", [])
                text = "".join(r.get("plain_text", "") for r in rich)
                if text:
                    out.append(text)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return out


class ReflectionStore:
    """Persistent reflections: Notion canonical, local mirror as fallback."""

    def __init__(self, page_id: str, mirror_path: str, auth_env_var: str = "NOTION_API_KEY"):
        self.mirror_path = mirror_path
        token = os.environ.get(auth_env_var)
        self.notion = _NotionClient(page_id, token)
        os.makedirs(os.path.dirname(os.path.abspath(mirror_path)), exist_ok=True)

    def load_reflections(self) -> List[str]:
        """Read prior reflections at session start. Returns the lines in context."""
        if self.notion.available:
            try:
                return self.notion.read_all()
            except Exception:
                pass  # fall through to mirror
        if os.path.exists(self.mirror_path):
            with open(self.mirror_path, "r", encoding="utf-8") as fh:
                return [ln.rstrip("\n") for ln in fh if ln.strip()]
        return []

    def add_reflection(
        self, text: str, session_id: str, ctx: Optional[str] = None
    ) -> tuple[str, bool]:
        """Append a reflection. Returns (sink, notion_ok).

        sink is 'notion' or 'mirror'; notion_ok is False if we fell back so the
        dispatcher can log a notion_unreachable fault.
        """
        refl = Reflection(text=text, ctx=ctx, session_id=session_id, ts=_utc_now())
        if self.notion.available:
            try:
                self.notion.append(refl)
                return "notion", True
            except Exception:
                self._append_mirror(refl)
                return "mirror", False
        self._append_mirror(refl)
        return "mirror", False

    def _append_mirror(self, refl: Reflection) -> None:
        new = not os.path.exists(self.mirror_path)
        with open(self.mirror_path, "a", encoding="utf-8") as fh:
            if new:
                fh.write("# Relay — Reflections (local mirror)\n\n")
                fh.write(
                    "> Offline mirror of the Notion page. Reconcile to Notion on the "
                    "next successful connection; Notion is canonical.\n\n"
                )
            fh.write(refl.as_line() + "\n")
