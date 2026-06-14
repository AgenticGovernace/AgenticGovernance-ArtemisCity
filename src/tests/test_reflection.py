"""Tests for the reflection engine (src/agents/artemis/reflection.py)."""

import sys

sys.modules.pop("src.agents.artemis.reflection", None)

import pytest

from src.agents.artemis.reflection import ConceptGraph, ConceptNode, ReflectionEngine


# ---------------------------------------------------------------------------
# ConceptNode
# ---------------------------------------------------------------------------
class TestConceptNode:
    """Provide the TestConceptNode abstraction used by this module."""

    def test_defaults(self):
        """Test that defaults.

        Returns:
            None: This function does not return a value.
        """
        node = ConceptNode(concept="memory")
        assert node.concept == "memory"
        assert node.contexts == []
        assert node.related_concepts == set()
        assert node.frequency == 0
        assert node.importance_score == 0.0

    def test_add_context(self):
        """Test that add context.

        Returns:
            None: This function does not return a value.
        """
        node = ConceptNode(concept="memory")
        node.add_context("we discussed memory")
        assert node.frequency == 1
        assert len(node.contexts) == 1

    def test_multiple_contexts(self):
        """Test that multiple contexts.

        Returns:
            None: This function does not return a value.
        """
        node = ConceptNode(concept="agents")
        node.add_context("ctx1")
        node.add_context("ctx2")
        node.add_context("ctx3")
        assert node.frequency == 3

    def test_relate_to(self):
        """Test that relate to.

        Returns:
            None: This function does not return a value.
        """
        node = ConceptNode(concept="memory")
        node.relate_to("vector")
        node.relate_to("obsidian")
        assert "vector" in node.related_concepts
        assert "obsidian" in node.related_concepts

    def test_relate_to_dedup(self):
        """Test that relate to dedup.

        Returns:
            None: This function does not return a value.
        """
        node = ConceptNode(concept="memory")
        node.relate_to("vector")
        node.relate_to("vector")
        assert len(node.related_concepts) == 1


# ---------------------------------------------------------------------------
# ConceptGraph
# ---------------------------------------------------------------------------
class TestConceptGraph:
    """Provide the TestConceptGraph abstraction used by this module."""

    @pytest.fixture
    def graph(self):
        """Graph.

        Returns:
            None: This function does not return a value.
        """
        return ConceptGraph()

    def test_add_concept_new(self, graph):
        """Test that add concept new.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("Memory", "context about memory")
        assert "memory" in graph.concepts
        assert graph.concepts["memory"].frequency == 1

    def test_add_concept_existing(self, graph):
        """Test that add concept existing.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("Memory", "ctx1")
        graph.add_concept("memory", "ctx2")  # same concept, different case
        assert graph.concepts["memory"].frequency == 2

    def test_relate_concepts(self, graph):
        """Test that relate concepts.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("Memory", "ctx")
        graph.add_concept("Vector", "ctx")
        graph.relate_concepts("Memory", "Vector")
        assert "vector" in graph.concepts["memory"].related_concepts
        assert "memory" in graph.concepts["vector"].related_concepts
        assert len(graph.concept_pairs) == 1

    def test_relate_nonexistent_concepts(self, graph):
        """Test that relate nonexistent concepts.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("Memory", "ctx")
        graph.relate_concepts("Memory", "Nonexistent")
        assert len(graph.concept_pairs) == 0

    def test_get_top_concepts(self, graph):
        """Test that get top concepts.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for word in ["alpha", "beta", "gamma"]:
            graph.add_concept(word, "ctx")
        # Boost gamma
        graph.concepts["gamma"].importance_score = 1.0
        top = graph.get_top_concepts(2)
        assert len(top) == 2
        assert top[0].concept == "gamma"

    def test_get_top_concepts_by_frequency(self, graph):
        """Test that get top concepts by frequency.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("rare", "ctx1")
        graph.add_concept("common", "ctx1")
        graph.add_concept("common", "ctx2")
        graph.add_concept("common", "ctx3")
        top = graph.get_top_concepts(1)
        assert top[0].concept == "common"

    def test_find_concept_clusters_connected(self, graph):
        """Test that find concept clusters connected.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("A", "ctx")
        graph.add_concept("B", "ctx")
        graph.add_concept("C", "ctx")
        graph.relate_concepts("A", "B")
        graph.relate_concepts("B", "C")
        clusters = graph.find_concept_clusters()
        assert len(clusters) == 1
        assert clusters[0] == {"a", "b", "c"}

    def test_find_concept_clusters_disjoint(self, graph):
        """Test that find concept clusters disjoint.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("A", "ctx")
        graph.add_concept("B", "ctx")
        graph.add_concept("C", "ctx")
        graph.add_concept("D", "ctx")
        graph.relate_concepts("A", "B")
        graph.relate_concepts("C", "D")
        clusters = graph.find_concept_clusters()
        assert len(clusters) == 2

    def test_find_concept_clusters_singletons_excluded(self, graph):
        """Test that find concept clusters singletons excluded.

        Args:
            graph: Graph value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        graph.add_concept("Alone", "ctx")
        clusters = graph.find_concept_clusters()
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# ReflectionEngine
# ---------------------------------------------------------------------------
class TestReflectionEngine:
    """Provide the TestReflectionEngine abstraction used by this module."""

    @pytest.fixture
    def engine(self):
        """Engine.

        Returns:
            None: This function does not return a value.
        """
        return ReflectionEngine()

    def test_initial_state(self, engine):
        """Test that initial state.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert engine.conversation_history == []
        assert len(engine.concept_graph.concepts) == 0

    def test_add_conversation_extracts_concepts(self, engine):
        """Test that add conversation extracts concepts.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.add_conversation("The memory system uses vector embeddings for recall")
        assert len(engine.concept_graph.concepts) > 0
        assert "memory" in engine.concept_graph.concepts

    def test_add_conversation_tracks_history(self, engine):
        """Test that add conversation tracks history.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.add_conversation("first")
        engine.add_conversation("second")
        assert len(engine.conversation_history) == 2

    def test_concept_extraction_filters_stopwords(self, engine):
        """Test that concept extraction filters stopwords.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        concepts = engine._extract_concepts("the and of to a in for is on with")
        assert concepts == []

    def test_concept_extraction_filters_short_words(self, engine):
        """Test that concept extraction filters short words.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        concepts = engine._extract_concepts("hi ok go do it be")
        assert concepts == []

    def test_concept_extraction_deduplicates(self, engine):
        """Test that concept extraction deduplicates.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        concepts = engine._extract_concepts("agent agent agent different")
        assert concepts.count("agent") == 1

    def test_relationship_identification(self, engine):
        """Test that relationship identification.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.add_conversation("memory and vector are closely related")
        # memory and vector should be related (within 50 chars)
        mem_node = engine.concept_graph.concepts.get("memory")
        if mem_node:
            assert "vector" in mem_node.related_concepts

    def test_synthesize_empty(self, engine):
        """Test that synthesize empty.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = engine.synthesize()
        assert "No conversations" in result

    def test_synthesize_with_conversations(self, engine):
        """Test that synthesize with conversations.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.add_conversation("The agent memory system handles knowledge storage")
        engine.add_conversation("Vector embeddings enable semantic memory recall")
        result = engine.synthesize()
        assert "Synthesis" in result
        assert "Key Themes" in result

    def test_synthesize_with_focus(self, engine):
        """Test that synthesize with focus.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.add_conversation("The memory system stores knowledge persistently")
        result = engine.synthesize(focus="memory")
        assert "Focused Insight" in result

    def test_synthesize_with_no_focus_match(self, engine):
        """Test that synthesize with no focus match.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.add_conversation("Agents process tasks efficiently")
        result = engine.synthesize(focus="zebra")
        assert "No direct connections" in result

    def test_build_narrative_empty(self, engine):
        """Test that build narrative empty.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        narrative = engine._build_narrative([], [])
        assert "still forming" in narrative.lower()

    def test_build_narrative_with_concepts(self, engine):
        """Test that build narrative with concepts.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        nodes = [ConceptNode(concept="memory"), ConceptNode(concept="agents")]
        narrative = engine._build_narrative(nodes, [])
        assert "memory" in narrative
        assert "agents" in narrative

    def test_build_narrative_with_clusters(self, engine):
        """Test that build narrative with clusters.

        Args:
            engine: Engine value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        engine.concept_graph.add_concept("alpha", "ctx")
        engine.concept_graph.add_concept("beta", "ctx")
        clusters = [{"alpha", "beta"}]
        nodes = [engine.concept_graph.concepts["alpha"]]
        narrative = engine._build_narrative(nodes, clusters)
        assert "clusters" in narrative.lower() or "alpha" in narrative.lower()
