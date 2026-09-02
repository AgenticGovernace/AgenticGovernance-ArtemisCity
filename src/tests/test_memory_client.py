"""Tests for the memory client (src/integration/memory_client.py)."""

import io
import json
import sys
from urllib.error import HTTPError, URLError

sys.modules.pop("src.integration.memory_client", None)

import pytest

from src.integration.memory_client import MCPOperation, MCPResponse, MemoryClient


# ---------------------------------------------------------------------------
# MCPOperation enum
# ---------------------------------------------------------------------------
class TestMCPOperation:
    """Provide the TestMCPOperation abstraction used by this module."""

    def test_values(self):
        """Test that values.

        Returns:
            None: This function does not return a value.
        """
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
    """Represent the response payload for the TestMCPResponse API contract."""

    def test_construction(self):
        """Test that construction.

        Returns:
            None: This function does not return a value.
        """
        r = MCPResponse(success=True, data={"key": "val"}, message="ok")
        assert r.success is True
        assert r.data == {"key": "val"}
        assert r.message == "ok"
        assert r.status_code == 200

    def test_from_json(self):
        """Test that from json.

        Returns:
            None: This function does not return a value.
        """
        json_data = {"success": True, "data": {"notes": []}, "message": "found"}
        r = MCPResponse.from_json(json_data, 200)
        assert r.success is True
        assert r.data == {"notes": []}
        assert r.status_code == 200

    def test_from_json_error(self):
        """Test that from json error.

        Returns:
            None: This function does not return a value.
        """
        json_data = {"success": False, "error": "not found"}
        r = MCPResponse.from_json(json_data, 404)
        assert r.success is False
        assert r.error == "not found"
        assert r.status_code == 404

    def test_from_json_defaults(self):
        """Test that from json defaults.

        Returns:
            None: This function does not return a value.
        """
        r = MCPResponse.from_json({}, 200)
        assert r.success is False
        assert r.data is None


# ---------------------------------------------------------------------------
# MemoryClient construction
# ---------------------------------------------------------------------------
class TestMemoryClientConstruction:
    """Provide the TestMemoryClientConstruction abstraction used by this module."""

    def test_missing_api_key_raises(self, monkeypatch):
        """Test that missing api key raises.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MCP_API_KEY"):
            MemoryClient(api_key="")

    def test_explicit_params(self):
        """Test that explicit params.

        Returns:
            None: This function does not return a value.
        """
        c = MemoryClient(base_url="http://localhost:9999", api_key="test-key")
        assert c.base_url == "http://localhost:9999"
        assert c.api_key == "test-key"

    def test_trailing_slash_stripped(self):
        """Test that trailing slash stripped.

        Returns:
            None: This function does not return a value.
        """
        c = MemoryClient(base_url="http://localhost:9999/", api_key="key")
        assert c.base_url == "http://localhost:9999"

    def test_timeout_default(self):
        """Test that timeout default.

        Returns:
            None: This function does not return a value.
        """
        c = MemoryClient(base_url="http://localhost", api_key="key")
        assert c.timeout == 30

    @pytest.mark.parametrize(
        "base_url",
        [
            "file:///etc/passwd",
            "ftp://example.test",
            "data:text/plain,secret",
            "//example.test",
            "localhost:3000",
            "http:///missing-host",
            "http://user:secret@example.test",
        ],
    )
    def test_rejects_non_http_or_malformed_base_urls(self, base_url):
        with pytest.raises(ValueError, match="MCP base URL"):
            MemoryClient(base_url=base_url, api_key="key")

    @pytest.mark.parametrize(
        "base_url",
        ["http://localhost", "https://memory.example.test/prefix", "HTTP://LOCALHOST"],
    )
    def test_accepts_http_and_https_base_urls(self, base_url):
        client = MemoryClient(base_url=base_url, api_key="key")

        assert client.base_url == base_url


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
    """Represent the request payload consumed by the TestMakeRequest API contract."""

    @pytest.fixture
    def client(self):
        """Client.

        Returns:
            None: This function does not return a value.
        """
        return MemoryClient(base_url="http://localhost:3000", api_key="test-key")

    def test_success(self, client, monkeypatch):
        """Test that success.

        Args:
            client: Client value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """

        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse({"success": True, "data": {"notes": []}})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is True

    def test_http_error_with_json_body(self, client, monkeypatch):
        """Test that http error with json body.

        Args:
            client: Client value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """

        def fake_urlopen(req, timeout=None):
            body = json.dumps({"success": False, "error": "bad request"}).encode()
            raise HTTPError(
                url="http://x",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(body),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert resp.status_code == 400
        assert "bad request" in resp.error

    def test_http_error_without_json_body(self, client, monkeypatch):
        """Test that http error without json body.

        Args:
            client: Client value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """

        def fake_urlopen(req, timeout=None):
            raise HTTPError(
                url="http://x",
                code=500,
                msg="Server Error",
                hdrs=None,
                fp=io.BytesIO(b"not json"),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert resp.status_code == 500

    def test_url_error(self, client, monkeypatch):
        """Test that url error.

        Args:
            client: Client value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """

        def fake_urlopen(req, timeout=None):
            raise URLError("Connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        resp = client._make_request(MCPOperation.LIST_NOTES)
        assert resp.success is False
        assert "Connection" in resp.error
        assert resp.status_code == 0

    def test_generic_exception(self, client, monkeypatch):
        """Test that generic exception.

        Args:
            client: Client value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """

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
    """Provide the TestAPIMethods abstraction used by this module."""

    @pytest.fixture
    def client(self, monkeypatch):
        """Client.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test that get context.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.get_context("notes/test.md")
        assert self._last_op == MCPOperation.GET_CONTEXT
        assert self._last_data == {"path": "notes/test.md"}

    def test_append_context(self, client):
        """Test that append context.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.append_context("notes/test.md", "new content")
        assert self._last_op == MCPOperation.APPEND_CONTEXT

    def test_update_note(self, client):
        """Test that update note.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.update_note("notes/test.md", "replaced")
        assert self._last_op == MCPOperation.UPDATE_NOTE

    def test_search_notes(self, client):
        """Test that search notes.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.search_notes("query", context_length=200)
        assert self._last_op == MCPOperation.SEARCH_NOTES
        assert self._last_data["contextLength"] == 200

    def test_list_notes_with_folder(self, client):
        """Test that list notes with folder.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.list_notes("daily")
        assert self._last_op == MCPOperation.LIST_NOTES
        assert self._last_data == {"folder": "daily"}

    def test_list_notes_no_folder(self, client):
        """Test that list notes no folder.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.list_notes()
        assert self._last_data == {}

    def test_delete_note(self, client):
        """Test that delete note.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.delete_note("notes/old.md")
        assert self._last_op == MCPOperation.DELETE_NOTE

    def test_manage_frontmatter(self, client):
        """Test that manage frontmatter.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.manage_frontmatter("note.md", "set", key="date", value="2025-01-01")
        assert self._last_op == MCPOperation.MANAGE_FRONTMATTER
        assert self._last_data["key"] == "date"

    def test_manage_tags(self, client):
        """Test that manage tags.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.manage_tags("note.md", "add", tags=["arch"])
        assert self._last_op == MCPOperation.MANAGE_TAGS
        assert self._last_data["tags"] == ["arch"]

    def test_search_replace(self, client):
        """Test that search replace.

        Args:
            client: Client value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        client.search_replace("note.md", "old", "new", regex=True)
        assert self._last_op == MCPOperation.SEARCH_REPLACE
        assert self._last_data["regex"] is True


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------
class TestHealthCheck:
    """Provide the TestHealthCheck abstraction used by this module."""

    def test_healthy(self, monkeypatch):
        """Test that healthy.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        c = MemoryClient(base_url="http://localhost:3000", api_key="key")

        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse({"status": "ok"}, status=200)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        assert c.health_check() is True

    def test_unhealthy(self, monkeypatch):
        """Test that unhealthy.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        c = MemoryClient(base_url="http://localhost:3000", api_key="key")

        def fake_urlopen(req, timeout=None):
            raise ConnectionError("refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        assert c.health_check() is False


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------
class TestConvenienceMethods:
    """Provide the TestConvenienceMethods abstraction used by this module."""

    def test_get_agent_context(self, monkeypatch):
        """Test that get agent context.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test that get agent context failure.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        c = MemoryClient(base_url="http://localhost", api_key="key")

        def fake_request(op, data=None):
            return MCPResponse(success=False, error="nope")

        monkeypatch.setattr(c, "_make_request", fake_request)
        resp = c.get_agent_context("artemis")
        assert resp.success is False

    def test_store_agent_context(self, monkeypatch):
        """Test that store agent context.

        Args:
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
