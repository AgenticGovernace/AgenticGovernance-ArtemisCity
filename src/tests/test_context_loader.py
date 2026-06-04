"""Tests for the context loader (src/integration/context_loader.py)."""

import sys

sys.modules.pop("src.integration.context_loader", None)

import pytest
from src.integration.context_loader import ContextEntry, ContextLoader
from src.integration.memory_client import MCPResponse


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
    """Provide the TestContextEntry abstraction used by this module.
    """
    def test_get_summary_short(self):
        """Test that get summary short.
        
        Returns:
            None: This function does not return a value.
        """
        entry = ContextEntry(path="a.md", content="short", tags=[], frontmatter={})
        assert entry.get_summary() == "short"

    def test_get_summary_truncated(self):
        """Test that get summary truncated.
        
        Returns:
            None: This function does not return a value.
        """
        entry = ContextEntry(path="a.md", content="x" * 300, tags=[], frontmatter={})
        s = entry.get_summary(200)
        assert len(s) == 203  # 200 + "..."
        assert s.endswith("...")

    def test_get_summary_exact_length(self):
        """Test that get summary exact length.
        
        Returns:
            None: This function does not return a value.
        """
        entry = ContextEntry(path="a.md", content="x" * 200, tags=[], frontmatter={})
        assert entry.get_summary(200) == "x" * 200

    def test_relevance_score(self):
        """Test that relevance score.
        
        Returns:
            None: This function does not return a value.
        """
        entry = ContextEntry(
            path="a.md", content="c", tags=[], frontmatter={}, relevance_score=0.95
        )
        assert entry.relevance_score == 0.95


# ---------------------------------------------------------------------------
# ContextLoader.load_note
# ---------------------------------------------------------------------------
class TestLoadNote:
    """Provide the TestLoadNote abstraction used by this module.
    """

    @pytest.fixture
    def client(self):
        """Client.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that load note success.
        
        Args:
            client: Client value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        loader = ContextLoader(memory_client=client)
        entry = loader.load_note("notes/test.md")
        assert entry is not None
        assert entry.content == "hello"
        assert entry.tags == ["arch"]
        assert entry.frontmatter == {"date": "2025-01-01"}

    def test_load_note_failure(self):
        """Test that load note failure.
        
        Returns:
            None: This function does not return a value.
        """
        client = _StubMemoryClient()
        client.set_response(
            "get_context", MCPResponse(success=False, error="not found")
        )
        loader = ContextLoader(memory_client=client)
        assert loader.load_note("missing.md") is None

    def test_load_note_no_tags(self, client):
        """Test that load note no tags.
        
        Args:
            client: Client value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        client.set_response("manage_tags", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        entry = loader.load_note("test.md")
        assert entry.tags == []

    def test_load_note_no_frontmatter(self, client):
        """Test that load note no frontmatter.
        
        Args:
            client: Client value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        client.set_response("manage_frontmatter", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        entry = loader.load_note("test.md")
        assert entry.frontmatter == {}


# ---------------------------------------------------------------------------
# ContextLoader.search_context
# ---------------------------------------------------------------------------
class TestSearchContext:
    """Provide the TestSearchContext abstraction used by this module.
    """
    def test_search_success(self):
        """Test that search success.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that search with limit.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that search failure.
        
        Returns:
            None: This function does not return a value.
        """
        client = _StubMemoryClient()
        client.set_response("search_notes", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.search_context("query") == []


# ---------------------------------------------------------------------------
# ContextLoader.load_folder_context
# ---------------------------------------------------------------------------
class TestLoadFolderContext:
    """Provide the TestLoadFolderContext abstraction used by this module.
    """
    def test_load_folder(self):
        """Test that load folder.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that load folder failure.
        
        Returns:
            None: This function does not return a value.
        """
        client = _StubMemoryClient()
        client.set_response("list_notes", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.load_folder_context("daily") == []


# ---------------------------------------------------------------------------
# ContextLoader.load_tagged_context
# ---------------------------------------------------------------------------
class TestLoadTaggedContext:
    """Provide the TestLoadTaggedContext abstraction used by this module.
    """
    def test_delegates_to_search(self):
        """Test that delegates to search.
        
        Returns:
            None: This function does not return a value.
        """
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
    """Provide the TestLoadAgentHistory abstraction used by this module.
    """
    def test_load_agent_history(self):
        """Test that load agent history.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that load agent history failure.
        
        Returns:
            None: This function does not return a value.
        """
        client = _StubMemoryClient()
        client.set_response("get_agent_context", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.load_agent_history("artemis") == []


# ---------------------------------------------------------------------------
# ContextLoader.get_context_summary
# ---------------------------------------------------------------------------
class TestGetContextSummary:
    """Provide the TestGetContextSummary abstraction used by this module.
    """

    @pytest.fixture
    def loader(self):
        """Loader.
        
        Returns:
            None: This function does not return a value.
        """
        return ContextLoader(memory_client=_StubMemoryClient())

    def test_empty(self, loader):
        """Test that empty.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        assert "No context" in loader.get_context_summary([])

    def test_normal(self, loader):
        """Test that normal.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that overflow.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
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
    """Provide the TestFilterByDateRange abstraction used by this module.
    """

    @pytest.fixture
    def loader(self):
        """Loader.
        
        Returns:
            None: This function does not return a value.
        """
        return ContextLoader(memory_client=_StubMemoryClient())

    def test_filter_with_dates(self, loader):
        """Test that filter with dates.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that filter no date in frontmatter.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        entries = [
            ContextEntry(path="a.md", content="", tags=[], frontmatter={}),
        ]
        filtered = loader.filter_by_date_range(entries, start_date="2025-01-01")
        assert filtered == []

    def test_filter_with_created_field(self, loader):
        """Test that filter with created field.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
        entries = [
            ContextEntry(
                path="a.md", content="", tags=[], frontmatter={"created": "2025-02-01"}
            ),
        ]
        filtered = loader.filter_by_date_range(entries, start_date="2025-01-01")
        assert len(filtered) == 1

    def test_filter_no_bounds(self, loader):
        """Test that filter no bounds.
        
        Args:
            loader: Loader value used by this operation.
        
        Returns:
            None: This function does not return a value.
        """
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
    """Provide the TestGetRelatedContext abstraction used by this module.
    """
    def test_get_related(self):
        """Test that get related.
        
        Returns:
            None: This function does not return a value.
        """
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
        """Test that get related note not found.
        
        Returns:
            None: This function does not return a value.
        """
        client = _StubMemoryClient()
        client.set_response("get_context", MCPResponse(success=False))
        loader = ContextLoader(memory_client=client)
        assert loader.get_related_context("missing.md") == []
