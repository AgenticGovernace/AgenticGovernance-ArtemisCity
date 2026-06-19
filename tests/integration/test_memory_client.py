"""Tests for the memory client (src/integration/memory_client.py)."""

import sys
import io
import json
import urllib.error

sys.modules.pop("integration.memory_client", None)

import pytest
from integration.memory_client import MCPOperation, MCPResponse, MemoryClient


# ---------------------------------------------------------------------------
# MCPOperation enum
# ---------------------------------------------------------------------------
class TestMCPOperation:
    def test_values(self):
        assert MCPOperation.GET_CONTEXT.value == "getContext"
        assert MCPOperation.APPEND_CONTEXT.value == "appendContext"
        assert MCPOperation.UPDATE_NOTE.value == "updateNote"
        assert MCPOperation.SEARCH_NOTES.value == "searchNotes"
        assert MCPOperation.LIST_NOTES.value == "listNotes"
        assert MCPOperation.DELETE_NOTE.value == "deleteNote"
        assert MCPOperation.MANAGE_FRONTMATTER.value == "manageFrontmatter"
        assert MCPOperation.MANAGE_TAGS.value == "manageTags"
        assert MCPOperation.SEARCH_REPLACE.value == "searchReplace"


# ---------------------------------------------------------------------------
# MCPResponse
# ---------------------------------------------------------------------------
class TestMCPResponse:
    def test_construction(self):
        r = MCPResponse(success=True, data={"key": "val"}, message="ok")
        assert r.success is True
        assert r.data == {"key": "val"}
        assert r.message == "ok"
        assert r.status_code == 200

    def test_from_json(self):
        json_data = {"success": True, "data": {"notes": []}, "message": "found"}
        r = MCPResponse.from_json(json_data, 200)
        assert r.success is True
        assert r.data == {"notes": []}
        assert r.status_code == 200

    def test_from_json_error(self):
        json_data = {"success": False, "error": "not found"}
        r = MCPResponse.from_json(json_data, 404)
        assert r.success is False
        assert r.error == "not found"
        assert r.status_code == 404

    def test_from_json_defaults(self):
        r = MCPResponse.from_json({}, 200)
        assert r.success is False
        assert r.data is None


# ---------------------------------------------------------------------------
# MemoryClient construction
# ---------------------------------------------------------------------------
class TestMemoryClientConstruction:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MCP_API_KEY"):
            MemoryClient(api_key="")

    def test_explicit_params(self):
        c = MemoryClient(base_url="http://localhost:9999", api_key="test-key")
        assert c.base_url == "http://localhost:9999"
        assert c.api_key == "test-key"

    def test_trailing_slash_stripped(self):
        c = MemoryClient(base_url="http://localhost:9999/", api_key="key")
        assert c.base_url == "http://localhost:9999"

    def test_timeout_default(self):
        c = MemoryClient(base_url="http://localhost", api_key="key")
        assert c.timeout == 30


# ---------------------------------------------------------------------------
# _make_request mocking
# ---------------------------------------------------------------------------
class _FakeHTTPResponse:
    """Simulates urllib response context manager."""

    def __init__(self, data, status=200):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestMakeRequest:
    @pytest.fixture
    def client(self):
        return MemoryClient(base_url="http://localhost:3000", api_key="test-key")

    def test_success(self, client, monkeypatch):
        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse({"success": True, "data": {"notes": []}})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is True

    def test_http_error_with_json_body(self, client, monkeypatch):
        def fake_urlopen(req, timeout=None):
            body = json.dumps({"success": False, "error": "bad request"}).encode()
            raise urllib.error.HTTPError(
                url="http://x", code=400, msg="Bad Request",
                hdrs=None, fp=io.BytesIO(body),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert resp.status_code == 400
        assert "bad request" in resp.error

    def test_http_error_without_json_body(self, client, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                url="http://x", code=500, msg="Server Error",
                hdrs=None, fp=io.BytesIO(b"not json"),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert resp.status_code == 500

    def test_url_error(self, client, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("Connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert "Connection" in resp.error
        assert resp.status_code == 0

    def test_generic_exception(self, client, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise RuntimeError("unexpected")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert "unexpected" in resp.error


# ---------------------------------------------------------------------------
# API method delegation
# ---------------------------------------------------------------------------
class TestAPIMethods:
    @pytest.fixture
    def client(self, monkeypatch):
        c = MemoryClient(base_url="http://localhost:3000", api_key="test-key")
        self._last_op = None
        self._last_data = None

        def fake_request(op, data=None):
            self._last_op = op
            self._last_data = data
            return MCPResponse(success=True, data={})

        monkeypatch.setattr(c, "_make_request", fake_request)
        return c

    def test_get_context(self, client):
        client.get_context("notes/test.md")
        assert self._last_op == MCPOperation.GET_CONTEXT
        assert self._last_data == {"path": "notes/test.md"}

    def test_append_context(self, client):
        client.append_context("notes/test.md", "new content")
        assert self._last_op == MCPOperation.APPEND_CONTEXT

    def test_update_note(self, client):
        client.update_note("notes/test.md", "replaced")
        assert self._last_op == MCPOperation.UPDATE_NOTE

    def test_search_notes(self, client):
        client.search_notes("query", context_length=200)
        assert self._last_op == MCPOperation.SEARCH_NOTES
        assert self._last_data["contextLength"] == 200

    def test_list_notes_with_folder(self, client):
        client.list_notes("daily")
        assert self._last_op == MCPOperation.LIST_NOTES
        assert self._last_data == {"folder": "daily"}

    def test_list_notes_no_folder(self, client):
        client.list_notes()
        assert self._last_data == {}

    def test_delete_note(self, client):
        client.delete_note("notes/old.md")
        assert self._last_op == MCPOperation.DELETE_NOTE

    def test_manage_frontmatter(self, client):
        client.manage_frontmatter("note.md", "set", key="date", value="2025-01-01")
        assert self._last_op == MCPOperation.MANAGE_FRONTMATTER
        assert self._last_data["key"] == "date"

    def test_manage_tags(self, client):
        client.manage_tags("note.md", "add", tags=["arch"])
        assert self._last_op == MCPOperation.MANAGE_TAGS
        assert self._last_data["tags"] == ["arch"]

    def test_search_replace(self, client):
        client.search_replace("note.md", "old", "new", regex=True)
        assert self._last_op == MCPOperation.SEARCH_REPLACE
        assert self._last_data["regex"] is True


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------
class TestHealthCheck:
    def test_healthy(self, monkeypatch):
        c = MemoryClient(base_url="http://localhost:3000", api_key="key")

        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse({"status": "ok"}, status=200)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        assert c.health_check() is True

    def test_unhealthy(self, monkeypatch):
        c = MemoryClient(base_url="http://localhost:3000", api_key="key")

        def fake_urlopen(req, timeout=None):
            raise ConnectionError("refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        assert c.health_check() is False


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------
class TestConvenienceMethods:
    def test_get_agent_context(self, monkeypatch):
        c = MemoryClient(base_url="http://localhost", api_key="key")

        def fake_request(op, data=None):
            return MCPResponse(
                success=True,
                data={"results": [{"path": f"r{i}.md"} for i in range(20)]},
            )

        monkeypatch.setattr(c, "_make_request", fake_request)
        resp = c.get_agent_context("artemis", limit=5)
        assert resp.success is True
        assert len(resp.data["results"]) == 5

    def test_get_agent_context_failure(self, monkeypatch):
        c = MemoryClient(base_url="http://localhost", api_key="key")

        def fake_request(op, data=None):
            return MCPResponse(success=False, error="nope")

        monkeypatch.setattr(c, "_make_request", fake_request)
        resp = c.get_agent_context("artemis")
        assert resp.success is False

    def test_store_agent_context(self, monkeypatch):
        c = MemoryClient(base_url="http://localhost", api_key="key")
        calls = []

        def fake_request(op, data=None):
            calls.append((op, data))
            return MCPResponse(success=True, data={})

        monkeypatch.setattr(c, "_make_request", fake_request)
        resp = c.store_agent_context("artemis", "important context")
        assert resp.success is True
        # Should have called append_context + manage_tags
        ops = [c[0] for c in calls]
        assert MCPOperation.APPEND_CONTEXT in ops
        assert MCPOperation.MANAGE_TAGS in ops
