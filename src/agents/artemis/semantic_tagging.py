"""Semantic tagging system for Artemis.

This module provides semantic tagging and citation capabilities for
organizing knowledge and referencing files, concepts, and conversations.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SemanticTag:
    """Represents a semantic tag with metadata.

    Attributes:
        tag: Tag name (e.g., 'architecture', 'memory-system')
        category: Tag category (e.g., 'concept', 'file', 'agent')
        references: Set of items tagged with this tag
        description: Optional description of tag meaning
    """

    tag: str
    category: str
    references: set[str] = field(default_factory=set)
    description: str | None = None

    def add_reference(self, reference: str) -> None:
        """Add a reference to this tag.

        Args:
            reference (str): Reference value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        self.references.add(reference)

    def __str__(self) -> str:
        """Return a string representation of the semantic tag."""
        return f"#{self.tag} ({self.category}) [{len(self.references)} refs]"


@dataclass
class Citation:
    """Represents a citation to a file or concept.

    Attributes:
        target: What is being cited (file path, concept name, etc.)
        citation_type: Type of citation (file, concept, agent, url)
        context: Context where citation appears
        line_number: Optional line number for file citations
    """

    target: str
    citation_type: str
    context: str | None = None
    line_number: int | None = None

    def format(self) -> str:
        """Format citation for display.

        Returns:
            str: String result produced by the operation.
        """
        if self.citation_type == "file":
            path = Path(self.target)
            if self.line_number:
                return f"[{path.name}:{self.line_number}]({self.target})"
            return f"[{path.name}]({self.target})"
        if self.citation_type == "concept":
            return f"*{self.target}*"
        if self.citation_type == "agent":
            return f"@{self.target}"
        return self.target


class SemanticTagger:
    """Semantic tagging and citation system.

    Provides capabilities for:
    - Tagging files, concepts, and conversations
    - Generating citations
    - Organizing knowledge by tags
    - Finding related items through tags
    """

    TAG_CATEGORIES = {
        "concept": "Abstract ideas and patterns",
        "file": "File paths and documents",
        "agent": "Agent names and roles",
        "protocol": "Communication protocols",
        "technology": "Technologies and frameworks",
        "status": "Status indicators",
    }

    def __init__(self):
        """Initialize semantic tagger."""
        self.tags: dict[str, SemanticTag] = {}
        self.citations: list[Citation] = []
        self.item_tags: dict[str, set[str]] = {}

    def tag_item(self, item: str, tags: list[str], category: str = "concept") -> None:
        """Tag an item with semantic tags.

        Args:
            item: Item to tag (file path, concept, etc.)
            tags: List of tag names
            category: Tag category

        Returns:
            None: This function does not return a value.
        """
        for tag_name in tags:
            tag_key = self._normalize_tag(tag_name)
            if tag_key not in self.tags:
                self.tags[tag_key] = SemanticTag(tag=tag_name, category=category)

            self.tags[tag_key].add_reference(item)

        if item not in self.item_tags:
            self.item_tags[item] = set()
        self.item_tags[item].update(self._normalize_tag(t) for t in tags)

    def add_citation(
        self,
        target: str,
        citation_type: str,
        context: str | None = None,
        line_number: int | None = None,
    ) -> Citation:
        """Add a citation.

        Args:
            target: Citation target
            citation_type: Type of citation
            context: Optional context
            line_number: Optional line number

        Returns:
            Created Citation object
        """
        citation = Citation(
            target=target,
            citation_type=citation_type,
            context=context,
            line_number=line_number,
        )
        self.citations.append(citation)
        return citation

    def get_items_by_tag(self, tag: str) -> list[str]:
        """Get all items with a specific tag.

        Args:
            tag (str): Tag value used by this operation.

        Returns:
            List[str]: List containing the resulting items.
        """
        tag_key = self._normalize_tag(tag)
        if tag_key in self.tags:
            return list(self.tags[tag_key].references)
        return []

    def get_tags_for_item(self, item: str) -> list[str]:
        """Get all tags for an item.

        Args:
            item (str): Single item under inspection.

        Returns:
            List[str]: List containing the resulting items.
        """
        if item in self.item_tags:
            return [
                self.tags[tag_key].tag
                for tag_key in self.item_tags[item]
                if tag_key in self.tags
            ]
        return []

    def find_related_items(self, item: str) -> list[str]:
        """Find items related to given item through shared tags.

        Args:
            item (str): Single item under inspection.

        Returns:
            List[str]: List containing the resulting items.
        """
        if item not in self.item_tags:
            return []

        related = set()
        item_tag_keys = self.item_tags[item]

        for tag_key in item_tag_keys:
            if tag_key in self.tags:
                related.update(self.tags[tag_key].references)

        related.discard(item)

        return list(related)

    def extract_tags_from_text(self, text: str) -> list[str]:
        """Extract hashtags from text.

        Args:
            text (str): Text value to parse, search, or transform.

        Returns:
            List[str]: List containing the resulting items.
        """
        pattern = r"#([\w-]+)"
        matches = re.findall(pattern, text)
        return matches

    def extract_citations_from_text(self, text: str) -> list[Citation]:
        """Extract citations from text.

        Args:
            text (str): Text value to parse, search, or transform.

        Returns:
            List[Citation]: List containing the resulting items.
        """
        citations = []

        file_pattern = r"(?:^|[\s(])([\\/~][\w\\/.-]+\.\w+)"
        for match in re.finditer(file_pattern, text):
            path = match.group(1)
            citations.append(
                Citation(
                    target=path,
                    citation_type="file",
                    context=text[max(0, match.start() - 20) : match.end() + 20],
                )
            )

        agent_pattern = r"@(\w+)"
        for match in re.finditer(agent_pattern, text):
            agent_name = match.group(1)
            citations.append(
                Citation(
                    target=agent_name,
                    citation_type="agent",
                    context=text[max(0, match.start() - 20) : match.end() + 20],
                )
            )

        return citations

    def generate_tag_summary(self) -> str:
        """Generate summary of all tags and their usage.

        Returns:
            str: String result produced by the operation.
        """
        if not self.tags:
            return "No tags defined yet."

        parts = ["## Semantic Tag Summary\n"]

        by_category: dict[str, list[SemanticTag]] = {}
        for tag in self.tags.values():
            if tag.category not in by_category:
                by_category[tag.category] = []
            by_category[tag.category].append(tag)

        for category, tags_list in sorted(by_category.items()):
            parts.append(f"### {category.title()}")
            for tag in sorted(tags_list, key=lambda t: len(t.references), reverse=True):
                parts.append(f"- #{tag.tag} ({len(tag.references)} references)")
            parts.append("")

        return "\n".join(parts)

    def get_citation_context(self, target: str) -> list[str]:
        """Get all contexts where a target was cited.

        Args:
            target (str): Target value used by this operation.

        Returns:
            List[str]: List containing the resulting items.
        """
        contexts = []
        for citation in self.citations:
            if citation.target == target and citation.context:
                contexts.append(citation.context)
        return contexts

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        """Normalize tag name for consistent storage."""
        normalized = tag.lstrip("#").lower().replace(" ", "-")
        return normalized

    def get_stats(self) -> dict:
        """Get tagging system statistics.

        Returns:
            Dict: Resulting Dict value produced by the operation.
        """
        return {
            "total_tags": len(self.tags),
            "total_citations": len(self.citations),
            "tagged_items": len(self.item_tags),
            "tags_by_category": {
                cat: sum(1 for t in self.tags.values() if t.category == cat)
                for cat in set(t.category for t in self.tags.values())
            },
        }
