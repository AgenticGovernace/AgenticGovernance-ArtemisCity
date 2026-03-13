"""Tests for the context loader (src/integration/context_loader.py)."""

import sys

sys.modules.pop("integration.context_loader", None)

import pytest
from integration.context_loader import ContextEntry, ContextLoader
from integration.memory_client import MCPResponse


# ---------------------------------------------------------------------------
# Stub MemoryClient
# ---------------------------------------------------------------------------
class _StubMemoryClient:
    """Returns canned MCPResponse objects for each method."""

    def __init__(self):
        self._responses = {}

    def set_response(self, method, response):
        self._responses[method] = response

    def _get(self, method, *args, **kwargs):
        return self._responses.get(
            method, MCPResponse(success=False, error="not configured")
        )

    def get_context(self, path):
        return self._get("get_context")

    def manage_tags(self, path, action, tags=None):
        return self._get("manage_tags")

    def manage_frontmatter(self, path, action, key=None, value=None):
        return self._get("manage_frontmatter")

    def search_notes(self, query, context_length=100):
        return self._get("search_notes")

    def list_notes(self, folder=""):
        return self._get("list_notes")

    def get_agent_context(self, agent_name, limit=10):
        return self._get("get_agent_context")


# ---------------------------------------------------------------------------
# ContextEntry
# ---------------------------------------------------------------------------
class TestContextEntry:
    def test_get_summary_short(self):
        entry = ContextEntry(path="a.md", content="short", tags=[], frontmatter={})
        assert entry.get_summary() == "short"

    def test_get_summary_truncated(self):
        entry = ContextEntry(path="a.md", content="x" * 300, tags=[], frontmatter={})
        s = entry.get_summary(200)
        assert len(s) == 203  # 200 + "..."
        assert s.endswith("...")

    def test_get_summary_exact_length(self):
        entry = ContextEntry(path="a.md", content="x" * 200, tags=[], frontmatter={})
        assert entry.get_summary(200) == "x" * 200

    def test_relevance_score(self):
        entry = ContextEntry(
            path="a.md", content="c", tags=[], frontmatter={}, relevance_score=0.95
        )
        assert entry.relevance_score == 0.95


# ---------------------------------------------------------------------------
# ContextLoader.load_note
# ---------------------------------------------------------------------------
class TestLoadNote:
    @pytest.fixture
    def client(self):
        c = _StubMemoryClient()
        c.set_response(
            "get_context", MCPResponse(success=True, data={"content": "hello"})
        )
        c.set_response(
            "manage_tags", MCPResponse(success=True, data={"tags": ["arch"]})
        )
        c.set_response(
            "manage_frontmatter",
            MCPResponse(success=True, data={"frontmatter": {"date": "2025-01-01"}}),
        )
        return c

    def test_load_note_success(self, client):
        loader = ContextLoader(memory_client=client)
        entry = loader.load_note("notes/test.md")
        assert entry is not None
        assert entry.content == "hello"
        assert entry.tags == ["arch"]
        assert entry.frontmatter == {"date": "2025-01-01"}

    def test_load_note_failure(self):
        client = _StubMemoryClient()
        client.set_response(
            "get_context", MCPResponse(success=False, error="not found")
        )
        loader = ContextLoader(memory_client=client)
        assert loader.load_note("missing.md") is None

    def test_load_note_no_tags(self, client):
        client.set_response("manage_tags", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        entry = loader.load_note("test.md")
        assert entry.tags == []

    def test_load_note_no_frontmatter(self, client):
        client.set_response("manage_frontmatter", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        entry = loader.load_note("test.md")
        assert entry.frontmatter == {}


# ---------------------------------------------------------------------------
# ContextLoader.search_context
# ---------------------------------------------------------------------------
class TestSearchContext:
    def test_search_success(self):
        client = _StubMemoryClient()
        client.set_response(
            "search_notes",
            MCPResponse(
                success=True,
                data={
                    "results": [
                        {
                            "path": "a.md",
                            "content": "match",
                            "tags": ["t"],
                            "score": 0.9,
                        },
                        {"path": "b.md", "content": "also", "tags": [], "score": 0.8},
                    ]
                },
            ),
        )
        loader = ContextLoader(memory_client=client)
        entries = loader.search_context("query")
        assert len(entries) == 2
        assert entries[0].path == "a.md"
        assert entries[0].relevance_score == 0.9

    def test_search_with_limit(self):
        client = _StubMemoryClient()
        client.set_response(
            "search_notes",
            MCPResponse(
                success=True,
                data={
                    "results": [{"path": f"{i}.md", "content": ""} for i in range(10)]
                },
            ),
        )
        loader = ContextLoader(memory_client=client)
        entries = loader.search_context("query", limit=3)
        assert len(entries) == 3

    def test_search_failure(self):
        client = _StubMemoryClient()
        client.set_response("search_notes", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.search_context("query") == []


# ---------------------------------------------------------------------------
# ContextLoader.load_folder_context
# ---------------------------------------------------------------------------
class TestLoadFolderContext:
    def test_load_folder(self):
        client = _StubMemoryClient()
        client.set_response(
            "list_notes",
            MCPResponse(success=True, data={"notes": ["a.md", "b.md"]}),
        )
        client.set_response(
            "get_context", MCPResponse(success=True, data={"content": "c"})
        )
        client.set_response("manage_tags", MCPResponse(success=False))
        client.set_response("manage_frontmatter", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        entries = loader.load_folder_context("daily")
        assert len(entries) == 2

    def test_load_folder_failure(self):
        client = _StubMemoryClient()
        client.set_response("list_notes", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.load_folder_context("daily") == []


# ---------------------------------------------------------------------------
# ContextLoader.load_tagged_context
# ---------------------------------------------------------------------------
class TestLoadTaggedContext:
    def test_delegates_to_search(self):
        client = _StubMemoryClient()
        client.set_response(
            "search_notes",
            MCPResponse(
                success=True,
                data={"results": [{"path": "a.md", "content": "tagged"}]},
            ),
        )
        loader = ContextLoader(memory_client=client)
        entries = loader.load_tagged_context("architecture")
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# ContextLoader.load_agent_history
# ---------------------------------------------------------------------------
class TestLoadAgentHistory:
    def test_load_agent_history(self):
        client = _StubMemoryClient()
        client.set_response(
            "get_agent_context",
            MCPResponse(
                success=True,
                data={"results": [{"path": "agents/ctx.md"}]},
            ),
        )
        client.set_response(
            "get_context", MCPResponse(success=True, data={"content": "hist"})
        )
        client.set_response("manage_tags", MCPResponse(success=False))
        client.set_response("manage_frontmatter", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        entries = loader.load_agent_history("artemis")
        assert len(entries) == 1

    def test_load_agent_history_failure(self):
        client = _StubMemoryClient()
        client.set_response("get_agent_context", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.load_agent_history("artemis") == []


# ---------------------------------------------------------------------------
# ContextLoader.get_context_summary
# ---------------------------------------------------------------------------
class TestGetContextSummary:
    @pytest.fixture
    def loader(self):
        return ContextLoader(memory_client=_StubMemoryClient())

    def test_empty(self, loader):
        assert "No context" in loader.get_context_summary([])

    def test_normal(self, loader):
        entries = [
            ContextEntry(
                path="a.md", content="hello world", tags=["tag1"], frontmatter={}
            ),
            ContextEntry(path="b.md", content="content", tags=[], frontmatter={}),
        ]
        summary = loader.get_context_summary(entries)
        assert "2 entries" in summary
        assert "a.md" in summary
        assert "tag1" in summary

    def test_overflow(self, loader):
        entries = [
            ContextEntry(path=f"{i}.md", content="c", tags=[], frontmatter={})
            for i in range(10)
        ]
        summary = loader.get_context_summary(entries, max_entries=3)
        assert "7 more" in summary


# ---------------------------------------------------------------------------
# ContextLoader.filter_by_date_range
# ---------------------------------------------------------------------------
class TestFilterByDateRange:
    @pytest.fixture
    def loader(self):
        return ContextLoader(memory_client=_StubMemoryClient())

    def test_filter_with_dates(self, loader):
        entries = [
            ContextEntry(
                path="a.md", content="", tags=[], frontmatter={"date": "2025-01-15"}
            ),
            ContextEntry(
                path="b.md", content="", tags=[], frontmatter={"date": "2025-03-01"}
            ),
            ContextEntry(
                path="c.md", content="", tags=[], frontmatter={"date": "2025-06-01"}
            ),
        ]
        filtered = loader.filter_by_date_range(
            entries, start_date="2025-01-01", end_date="2025-04-01"
        )
        assert len(filtered) == 2
        paths = {e.path for e in filtered}
        assert paths == {"a.md", "b.md"}

    def test_filter_no_date_in_frontmatter(self, loader):
        entries = [
            ContextEntry(path="a.md", content="", tags=[], frontmatter={}),
        ]
        filtered = loader.filter_by_date_range(entries, start_date="2025-01-01")
        assert filtered == []

    def test_filter_with_created_field(self, loader):
        entries = [
            ContextEntry(
                path="a.md", content="", tags=[], frontmatter={"created": "2025-02-01"}
            ),
        ]
        filtered = loader.filter_by_date_range(entries, start_date="2025-01-01")
        assert len(filtered) == 1

    def test_filter_no_bounds(self, loader):
        entries = [
            ContextEntry(
                path="a.md", content="", tags=[], frontmatter={"date": "2025-01-01"}
            ),
        ]
        filtered = loader.filter_by_date_range(entries)
        assert len(filtered) == 1


# ---------------------------------------------------------------------------
# ContextLoader.get_related_context
# ---------------------------------------------------------------------------
class TestGetRelatedContext:
    def test_get_related(self):
        client = _StubMemoryClient()
        client.set_response(
            "get_context", MCPResponse(success=True, data={"content": "c"})
        )
        client.set_response(
            "manage_tags", MCPResponse(success=True, data={"tags": ["arch"]})
        )
        client.set_response("manage_frontmatter", MCPResponse(success=False))
        client.set_response(
            "search_notes",
            MCPResponse(
                success=True,
                data={
                    "results": [
                        {"path": "related.md", "content": "r"},
                        {"path": "notes/test.md", "content": "self"},
                    ]
                },
            ),
        )
        loader = ContextLoader(memory_client=client)
        related = loader.get_related_context("notes/test.md")
        paths = [e.path for e in related]
        assert "notes/test.md" not in paths  # self excluded

    def test_get_related_note_not_found(self):
        client = _StubMemoryClient()
        client.set_response("get_context", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.get_related_context("missing.md") == []
