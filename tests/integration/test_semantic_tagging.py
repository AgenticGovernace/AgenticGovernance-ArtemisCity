"""Tests for semantic tagging (src/agents/artemis/semantic_tagging.py)."""

import sys

sys.modules.pop("agents.artemis.semantic_tagging", None)

import pytest
from agents.artemis.semantic_tagging import Citation, SemanticTag, SemanticTagger


# ---------------------------------------------------------------------------
# SemanticTag
# ---------------------------------------------------------------------------
class TestSemanticTag:
    def test_creation(self):
        tag = SemanticTag(tag="architecture", category="concept")
        assert tag.tag == "architecture"
        assert tag.category == "concept"
        assert tag.references == set()
        assert tag.description is None

    def test_add_reference(self):
        tag = SemanticTag(tag="arch", category="concept")
        tag.add_reference("file1.py")
        tag.add_reference("file2.py")
        assert len(tag.references) == 2

    def test_add_reference_dedup(self):
        tag = SemanticTag(tag="arch", category="concept")
        tag.add_reference("file1.py")
        tag.add_reference("file1.py")
        assert len(tag.references) == 1

    def test_str(self):
        tag = SemanticTag(tag="arch", category="concept")
        tag.add_reference("a")
        tag.add_reference("b")
        s = str(tag)
        assert "#arch" in s
        assert "concept" in s
        assert "2 refs" in s


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------
class TestCitation:
    def test_file_citation(self):
        c = Citation(target="/src/main.py", citation_type="file")
        assert "main.py" in c.format()
        assert "/src/main.py" in c.format()

    def test_file_citation_with_line(self):
        c = Citation(target="/src/main.py", citation_type="file", line_number=42)
        formatted = c.format()
        assert "main.py:42" in formatted

    def test_concept_citation(self):
        c = Citation(target="memory bus", citation_type="concept")
        assert c.format() == "*memory bus*"

    def test_agent_citation(self):
        c = Citation(target="artemis", citation_type="agent")
        assert c.format() == "@artemis"

    def test_url_citation(self):
        c = Citation(target="https://example.com", citation_type="url")
        assert c.format() == "https://example.com"


# ---------------------------------------------------------------------------
# SemanticTagger
# ---------------------------------------------------------------------------
class TestSemanticTagger:
    @pytest.fixture
    def tagger(self):
        return SemanticTagger()

    def test_initial_state(self, tagger):
        assert tagger.tags == {}
        assert tagger.citations == []
        assert tagger.item_tags == {}

    def test_tag_item_single(self, tagger):
        tagger.tag_item("file.py", ["architecture"])
        assert "architecture" in tagger.tags
        assert "file.py" in tagger.tags["architecture"].references
        assert "file.py" in tagger.item_tags

    def test_tag_item_multiple_tags(self, tagger):
        tagger.tag_item("file.py", ["architecture", "memory"])
        assert len(tagger.tags) == 2
        assert len(tagger.item_tags["file.py"]) == 2

    def test_tag_item_with_category(self, tagger):
        tagger.tag_item("artemis", ["overseer"], category="agent")
        assert tagger.tags["overseer"].category == "agent"

    def test_add_citation(self, tagger):
        c = tagger.add_citation("/src/main.py", "file", context="in main", line_number=10)
        assert isinstance(c, Citation)
        assert len(tagger.citations) == 1
        assert c.target == "/src/main.py"
        assert c.line_number == 10

    def test_get_items_by_tag(self, tagger):
        tagger.tag_item("a.py", ["core"])
        tagger.tag_item("b.py", ["core"])
        tagger.tag_item("c.py", ["other"])
        items = tagger.get_items_by_tag("core")
        assert set(items) == {"a.py", "b.py"}

    def test_get_items_by_tag_nonexistent(self, tagger):
        assert tagger.get_items_by_tag("nope") == []

    def test_get_tags_for_item(self, tagger):
        tagger.tag_item("file.py", ["arch", "memory"])
        tags = tagger.get_tags_for_item("file.py")
        assert set(tags) == {"arch", "memory"}

    def test_get_tags_for_item_nonexistent(self, tagger):
        assert tagger.get_tags_for_item("nope.py") == []

    def test_find_related_items(self, tagger):
        tagger.tag_item("a.py", ["core"])
        tagger.tag_item("b.py", ["core"])
        tagger.tag_item("c.py", ["other"])
        related = tagger.find_related_items("a.py")
        assert "b.py" in related
        assert "a.py" not in related  # self excluded

    def test_find_related_items_nonexistent(self, tagger):
        assert tagger.find_related_items("nope.py") == []

    def test_extract_tags_from_text(self, tagger):
        text = "This is about #architecture and #memory-bus design"
        tags = tagger.extract_tags_from_text(text)
        assert "architecture" in tags
        assert "memory-bus" in tags

    def test_extract_tags_no_tags(self, tagger):
        assert tagger.extract_tags_from_text("plain text") == []

    def test_generate_tag_summary_empty(self, tagger):
        assert "No tags" in tagger.generate_tag_summary()

    def test_generate_tag_summary_with_tags(self, tagger):
        tagger.tag_item("a.py", ["core"], category="concept")
        tagger.tag_item("b.py", ["core"], category="concept")
        tagger.tag_item("c.py", ["file-util"], category="file")
        summary = tagger.generate_tag_summary()
        assert "Semantic Tag Summary" in summary
        assert "Concept" in summary
        assert "File" in summary
        assert "#core" in summary
        assert "2 references" in summary

    def test_get_citation_context(self, tagger):
        tagger.add_citation("target1", "file", context="first mention")
        tagger.add_citation("target1", "file", context="second mention")
        tagger.add_citation("other", "file", context="not this")
        contexts = tagger.get_citation_context("target1")
        assert len(contexts) == 2
        assert "first mention" in contexts

    def test_get_citation_context_no_context(self, tagger):
        tagger.add_citation("target1", "file")
        assert tagger.get_citation_context("target1") == []

    def test_normalize_tag(self):
        assert SemanticTagger._normalize_tag("#Architecture") == "architecture"
        assert SemanticTagger._normalize_tag("memory bus") == "memory-bus"
        assert SemanticTagger._normalize_tag("##double") == "double"

    def test_get_stats(self, tagger):
        tagger.tag_item("a.py", ["core"], category="concept")
        tagger.add_citation("x", "file")
        stats = tagger.get_stats()
        assert stats["total_tags"] == 1
        assert stats["total_citations"] == 1
        assert stats["tagged_items"] == 1
        assert stats["tags_by_category"]["concept"] == 1
