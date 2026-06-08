"""Artemis persona-backed agent for MCP."""

from typing import Dict, List, Optional

from .artemis import ArtemisPersona, ReflectionEngine, SemanticTagger
from .base_agent import BaseAgent
from .llm_agent import LLMAgent


class ArtemisAgent(BaseAgent):
    """Agent that applies the Artemis persona to synthesize context and themes."""

    def __init__(
        self,
        name: str = "Artemis Agent",
        persona: Optional[ArtemisPersona] = None,
        reflection_engine: Optional[ReflectionEngine] = None,
        semantic_tagger: Optional[SemanticTagger] = None,
    ):
        super().__init__(name, capabilities=["system_management", "agent_coordination"])
        self.persona = persona or ArtemisPersona()
        self.reflection_engine = reflection_engine or ReflectionEngine()
        self.semantic_tagger = semantic_tagger or SemanticTagger()
        self.llm_agent = LLMAgent()

    def perform_task(self, task_context: Dict) -> Dict:
        """Perform task.

        Args:
            task_context (Dict): Structured task context passed to the agent.

        Returns:
            Dict: Resulting Dict value produced by the operation.
        """
        title = (
            task_context.get("title") or task_context.get("task_id") or "Artemis Task"
        )
        query = task_context.get("query") or task_context.get("content") or title
        atp_mode = task_context.get("atp_mode", "")
        request_feedback = task_context.get("request_feedback", True)

        content_blocks: List[str] = []
        for key in ("context", "content"):
            value = task_context.get(key)
            if value:
                content_blocks.append(str(value))
        content = "\n\n".join(content_blocks).strip()

        self.report_status(f"Reviewing task '{title}' with Artemis persona...")

        concept_names: List[str] = []
        tags: List[str] = []
        narrative = "No conversations to synthesize yet."

        if content:
            self.reflection_engine.add_conversation(content)
            concepts = self.reflection_engine.concept_graph.get_top_concepts(5)
            concept_names = [c.concept for c in concepts]
            tags = self.semantic_tagger.extract_tags_from_text(content)
            narrative = self.reflection_engine.synthesize(focus=title)
            self.persona.add_context_memory(content[:500])

        persona_context = {
            "query": query,
            "atp_mode": atp_mode,
            "request_feedback": request_feedback,
        }

        base_summary = None
        if task_context.get("disable_llm_delegate") is not True:
            llm_result = self.llm_agent.perform_task(
                {
                    "task_id": task_context.get("task_id"),
                    "system_prompt": (
                        "You are an orchestration assistant. Provide a practical response "
                        "that helps coordinate next actions."
                    ),
                    "prompt": content or query,
                    "temperature": task_context.get("temperature", 0.2),
                    "max_tokens": task_context.get("max_tokens", 500),
                    "model": task_context.get("model"),
                }
            )
            if llm_result.get("status") == "success":
                base_summary = str(llm_result.get("summary", "")).strip()

        if not base_summary:
            base_summary = (
                f"Artemis reviewed '{title}'. "
                f"Initial themes: {', '.join(concept_names) if concept_names else 'still forming'}."
            )
        formatted_summary = self.persona.format_response(base_summary, persona_context)

        self.report_status("Artemis synthesis complete.")

        return {
            "status": "success",
            "summary": formatted_summary,
            "narrative": narrative,
            "semantic_tags": tags,
            "concepts": concept_names,
            "persona_context": self.persona.get_personality_context(),
            "recent_context": self.persona.get_recent_context(),
        }
