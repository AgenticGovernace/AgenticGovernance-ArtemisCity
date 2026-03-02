"""Tests for the reflection engine (src/agents/artemis/reflection.py)."""

import sys

sys.modules.pop("agents.artemis.reflection", None)

import pytest
from agents.artemis.reflection import ConceptGraph, ConceptNode, ReflectionEngine


# ---------------------------------------------------------------------------
# ConceptNode
# ---------------------------------------------------------------------------
class TestConceptNode:
    def test_defaults(self):
        node = ConceptNode(concept="memory")
        assert node.concept == "memory"
        assert node.contexts == []
        assert node.related_concepts == set()
        assert node.frequency == 0
        assert node.importance_score == 0.0

    def test_add_context(self):
        node = ConceptNode(concept="memory")
        node.add_context("we discussed memory")
        assert node.frequency == 1
        assert len(node.contexts) == 1

    def test_multiple_contexts(self):
        node = ConceptNode(concept="agents")
        node.add_context("ctx1")
        node.add_context("ctx2")
        node.add_context("ctx3")
        assert node.frequency == 3

    def test_relate_to(self):
        node = ConceptNode(concept="memory")
        node.relate_to("vector")
        node.relate_to("obsidian")
        assert "vector" in node.related_concepts
        assert "obsidian" in node.related_concepts

    def test_relate_to_dedup(self):
        node = ConceptNode(concept="memory")
        node.relate_to("vector")
        node.relate_to("vector")
        assert len(node.related_concepts) == 1


# ---------------------------------------------------------------------------
# ConceptGraph
# ---------------------------------------------------------------------------
class TestConceptGraph:
    @pytest.fixture
    def graph(self):
        return ConceptGraph()

    def test_add_concept_new(self, graph):
        graph.add_concept("Memory", "context about memory")
        assert "memory" in graph.concepts
        assert graph.concepts["memory"].frequency == 1

    def test_add_concept_existing(self, graph):
        graph.add_concept("Memory", "ctx1")
        graph.add_concept("memory", "ctx2")  # same concept, different case
        assert graph.concepts["memory"].frequency == 2

    def test_relate_concepts(self, graph):
        graph.add_concept("Memory", "ctx")
        graph.add_concept("Vector", "ctx")
        graph.relate_concepts("Memory", "Vector")
        assert "vector" in graph.concepts["memory"].related_concepts
        assert "memory" in graph.concepts["vector"].related_concepts
        assert len(graph.concept_pairs) == 1

    def test_relate_nonexistent_concepts(self, graph):
        graph.add_concept("Memory", "ctx")
        graph.relate_concepts("Memory", "Nonexistent")
        assert len(graph.concept_pairs) == 0

    def test_get_top_concepts(self, graph):
        for word in ["alpha", "beta", "gamma"]:
            graph.add_concept(word, "ctx")
        # Boost gamma
        graph.concepts["gamma"].importance_score = 1.0
        top = graph.get_top_concepts(2)
        assert len(top) == 2
        assert top[0].concept == "gamma"

    def test_get_top_concepts_by_frequency(self, graph):
        graph.add_concept("rare", "ctx1")
        graph.add_concept("common", "ctx1")
        graph.add_concept("common", "ctx2")
        graph.add_concept("common", "ctx3")
        top = graph.get_top_concepts(1)
        assert top[0].concept == "common"

    def test_find_concept_clusters_connected(self, graph):
        graph.add_concept("A", "ctx")
        graph.add_concept("B", "ctx")
        graph.add_concept("C", "ctx")
        graph.relate_concepts("A", "B")
        graph.relate_concepts("B", "C")
        clusters = graph.find_concept_clusters()
        assert len(clusters) == 1
        assert clusters[0] == {"a", "b", "c"}

    def test_find_concept_clusters_disjoint(self, graph):
        graph.add_concept("A", "ctx")
        graph.add_concept("B", "ctx")
        graph.add_concept("C", "ctx")
        graph.add_concept("D", "ctx")
        graph.relate_concepts("A", "B")
        graph.relate_concepts("C", "D")
        clusters = graph.find_concept_clusters()
        assert len(clusters) == 2

    def test_find_concept_clusters_singletons_excluded(self, graph):
        graph.add_concept("Alone", "ctx")
        clusters = graph.find_concept_clusters()
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# ReflectionEngine
# ---------------------------------------------------------------------------
class TestReflectionEngine:
    @pytest.fixture
    def engine(self):
        return ReflectionEngine()

    def test_initial_state(self, engine):
        assert engine.conversation_history == []
        assert len(engine.concept_graph.concepts) == 0

    def test_add_conversation_extracts_concepts(self, engine):
        engine.add_conversation("The memory system uses vector embeddings for recall")
        assert len(engine.concept_graph.concepts) > 0
        assert "memory" in engine.concept_graph.concepts

    def test_add_conversation_tracks_history(self, engine):
        engine.add_conversation("first")
        engine.add_conversation("second")
        assert len(engine.conversation_history) == 2

    def test_concept_extraction_filters_stopwords(self, engine):
        concepts = engine._extract_concepts("the and of to a in for is on with")
        assert concepts == []

    def test_concept_extraction_filters_short_words(self, engine):
        concepts = engine._extract_concepts("hi ok go do it be")
        assert concepts == []

    def test_concept_extraction_deduplicates(self, engine):
        concepts = engine._extract_concepts("agent agent agent different")
        assert concepts.count("agent") == 1

    def test_relationship_identification(self, engine):
        engine.add_conversation("memory and vector are closely related")
        # memory and vector should be related (within 50 chars)
        mem_node = engine.concept_graph.concepts.get("memory")
        if mem_node:
            assert "vector" in mem_node.related_concepts

    def test_synthesize_empty(self, engine):
        result = engine.synthesize()
        assert "No conversations" in result

    def test_synthesize_with_conversations(self, engine):
        engine.add_conversation("The agent memory system handles knowledge storage")
        engine.add_conversation("Vector embeddings enable semantic memory recall")
        result = engine.synthesize()
        assert "Synthesis" in result
        assert "Key Themes" in result

    def test_synthesize_with_focus(self, engine):
        engine.add_conversation("The memory system stores knowledge persistently")
        result = engine.synthesize(focus="memory")
        assert "Focused Insight" in result

    def test_synthesize_with_no_focus_match(self, engine):
        engine.add_conversation("Agents process tasks efficiently")
        result = engine.synthesize(focus="zebra")
        assert "No direct connections" in result

    def test_build_narrative_empty(self, engine):
        narrative = engine._build_narrative([], [])
        assert "still forming" in narrative.lower()

    def test_build_narrative_with_concepts(self, engine):
        nodes = [ConceptNode(concept="memory"), ConceptNode(concept="agents")]
        narrative = engine._build_narrative(nodes, [])
        assert "memory" in narrative
        assert "agents" in narrative

    def test_build_narrative_with_clusters(self, engine):
        engine.concept_graph.add_concept("alpha", "ctx")
        engine.concept_graph.add_concept("beta", "ctx")
        clusters = [{"alpha", "beta"}]
        nodes = [engine.concept_graph.concepts["alpha"]]
        narrative = engine._build_narrative(nodes, clusters)
        assert "clusters" in narrative.lower() or "alpha" in narrative.lower()
