"""Reflection and synthesis capabilities for Artemis.

This module implements idea synthesis, pattern recognition, and
narrative building from multiple conversation threads.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ConceptNode:
    """Represents a concept extracted from conversations.

    Attributes:
        concept: The concept text
        contexts: List of contexts where concept appeared
        related_concepts: Set of related concept names
        frequency: Number of times concept appeared
        importance_score: Calculated importance (0-1)
    """

    concept: str
    contexts: List[str] = field(default_factory=list)
    related_concepts: Set[str] = field(default_factory=set)
    frequency: int = 0
    importance_score: float = 0.0

    def add_context(self, context: str) -> None:
        """Add a context where this concept appeared."""
        self.contexts.append(context)
        self.frequency += 1

    def relate_to(self, other_concept: str) -> None:
        """Mark another concept as related."""
        self.related_concepts.add(other_concept)


@dataclass
class ConceptGraph:
    """Graph of concepts and their relationships.

    Attributes:
        concepts: Dictionary of concept name to ConceptNode
        concept_pairs: Set of related concept pairs
    """

    concepts: Dict[str, ConceptNode] = field(default_factory=dict)
    concept_pairs: Set[Tuple[str, str]] = field(default_factory=set)

    def add_concept(self, concept: str, context: str) -> None:
        """Add or update a concept in the graph.

        Args:
            concept: Concept text
            context: Context where concept appeared
        """
        concept_key = concept.lower()
        if concept_key not in self.concepts:
            self.concepts[concept_key] = ConceptNode(concept=concept)

        self.concepts[concept_key].add_context(context)

    def relate_concepts(self, concept1: str, concept2: str) -> None:
        """Create relationship between two concepts.

        Args:
            concept1: First concept
            concept2: Second concept
        """
        key1 = concept1.lower()
        key2 = concept2.lower()

        if key1 in self.concepts and key2 in self.concepts:
            self.concepts[key1].relate_to(key2)
            self.concepts[key2].relate_to(key1)

            pair = tuple(sorted([key1, key2]))
            self.concept_pairs.add(pair)

    def get_top_concepts(self, n: int = 10) -> List[ConceptNode]:
        """Get top N concepts by importance.

        Args:
            n: Number of concepts to return

        Returns:
            List of top ConceptNode objects
        """
        sorted_concepts = sorted(
            self.concepts.values(),
            key=lambda c: (c.importance_score, c.frequency),
            reverse=True,
        )
        return sorted_concepts[:n]

    def find_concept_clusters(self) -> List[Set[str]]:
        """Find clusters of related concepts.

        Returns:
            List of concept clusters (sets of concept names)
        """
        visited = set()
        clusters = []

        def dfs(concept_key: str, cluster: Set[str]) -> None:
            """Depth-first search to find connected concepts."""
            if concept_key in visited:
                return

            visited.add(concept_key)
            cluster.add(concept_key)

            if concept_key in self.concepts:
                for related in self.concepts[concept_key].related_concepts:
                    dfs(related, cluster)

        for concept_key in self.concepts:
            if concept_key not in visited:
                cluster = set()
                dfs(concept_key, cluster)
                if len(cluster) > 1:
                    clusters.append(cluster)

        return clusters


class ReflectionEngine:
    """Engine for synthesizing ideas and finding patterns.

    Capabilities:
    - Extract key concepts from conversations
    - Identify relationships between concepts
    - Generate unified narratives
    - Find patterns across discussions
    """

    def __init__(self):
        """Initialize reflection engine."""
        self.concept_graph = ConceptGraph()
        self.conversation_history: List[str] = []

    def add_conversation(self, text: str) -> None:
        """Add a conversation to the reflection corpus.

        Args:
            text: Conversation text to analyze
        """
        self.conversation_history.append(text)

        concepts = self._extract_concepts(text)

        for concept in concepts:
            self.concept_graph.add_concept(concept, text)

        self._identify_relationships(concepts, text)

    def synthesize(self, focus: Optional[str] = None) -> str:
        """Synthesize insights from conversation history.

        Args:
            focus: Optional focus area for synthesis

        Returns:
            Synthesized narrative
        """
        if not self.conversation_history:
            return "No conversations to synthesize yet."

        top_concepts = self.concept_graph.get_top_concepts(10)
        clusters = self.concept_graph.find_concept_clusters()

        parts = ["## Synthesis of Recent Conversations\n"]

        if top_concepts:
            parts.append("### Key Themes")
            for i, concept in enumerate(top_concepts[:5], 1):
                parts.append(
                    f"{i}. **{concept.concept}** (appeared {concept.frequency} times)"
                )
            parts.append("")

        if clusters:
            parts.append("### Connected Ideas")
            for i, cluster in enumerate(clusters[:3], 1):
                concept_names = [
                    self.concept_graph.concepts[c].concept for c in cluster
                ]
                parts.append(f"{i}. {' ↔ '.join(concept_names[:5])}")
            parts.append("")

        parts.append("### Emerging Narrative")
        narrative = self._build_narrative(top_concepts, clusters)
        parts.append(narrative)

        if focus:
            parts.append("\n### Focused Insight")
            parts.append(self._generate_focus_section(focus, top_concepts))

        return "\n".join(parts)

    def _build_narrative(
        self, top_concepts: List[ConceptNode], clusters: List[Set[str]]
    ) -> str:
        """Build narrative from concepts and clusters."""
        narrative_parts = []

        if top_concepts:
            top_concept_names = [c.concept for c in top_concepts[:3]]
            narrative_parts.append(
                f"The main threads revolve around {'; '.join(top_concept_names)}."
            )

        if clusters:
            cluster_descriptions = []
            for cluster in clusters[:2]:
                names = [self.concept_graph.concepts[c].concept for c in cluster]
                cluster_descriptions.append(" ↔ ".join(names[:4]))
            if cluster_descriptions:
                narrative_parts.append(
                    f"Concept clusters highlight connections such as {', '.join(cluster_descriptions)}."
                )

        if not narrative_parts:
            narrative_parts.append(
                "Discussions are still forming; no strong themes have emerged yet."
            )

        return " ".join(narrative_parts)

    def _generate_focus_section(
        self, focus: str, top_concepts: List[ConceptNode]
    ) -> str:
        """Generate insights focused on a specific area."""
        focus_lower = focus.lower()
        related = []
        for concept in top_concepts:
            if focus_lower in concept.concept.lower():
                related.append(concept.concept)
        if related:
            return f"The focus area '{focus}' intersects with: {', '.join(related)}."
        return f"No direct connections found for focus area '{focus}', but it may relate to emerging themes."

    def _extract_concepts(self, text: str) -> List[str]:
        """Extract potential concepts from text."""
        normalized = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
        words = normalized.split()
        stopwords = {
            "the",
            "and",
            "of",
            "to",
            "a",
            "in",
            "for",
            "is",
            "on",
            "with",
            "that",
            "by",
            "this",
            "it",
            "from",
            "as",
            "are",
            "an",
            "be",
            "or",
            "at",
        }
        candidates = [w for w in words if len(w) > 3 and w not in stopwords]
        return list(dict.fromkeys(candidates))

    def _identify_relationships(self, concepts: List[str], text: str) -> None:
        """Identify relationships between concepts in the same text."""
        for i, concept in enumerate(concepts):
            for related in concepts[i + 1 :]:
                if self._concepts_are_related(concept, related, text):
                    self.concept_graph.relate_concepts(concept, related)

    def _concepts_are_related(self, concept1: str, concept2: str, text: str) -> bool:
        """Determine if two concepts are related based on proximity."""
        pattern = rf"{concept1}.{{0,50}}{concept2}|{concept2}.{{0,50}}{concept1}"
        return bool(re.search(pattern, text, re.IGNORECASE | re.DOTALL))
