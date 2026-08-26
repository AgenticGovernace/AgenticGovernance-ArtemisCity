"""Agent package exports for Artemis City.

Exports are resolved lazily so importing ``src.agents.base_agent`` does not
load optional agent implementations and their provider dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .artemis import (  # noqa: F401 - re-exported
        ArtemisPersona,
        Citation,
        ConceptGraph,
        ConceptNode,
        ReflectionEngine,
        ResponseMode,
        SemanticTag,
        SemanticTagger,
    )
    from .artemis_agent import ArtemisAgent  # noqa: F401 - re-exported
    from .base_agent import BaseAgent  # noqa: F401 - re-exported
    from .llm_agent import LLMAgent  # noqa: F401 - re-exported
    from .research_agent import ResearchAgent  # noqa: F401 - re-exported
    from .summarizer_agent import SummarizerAgent  # noqa: F401 - re-exported

_LAZY_EXPORTS = {
    "ArtemisPersona": ".artemis",
    "ResponseMode": ".artemis",
    "ReflectionEngine": ".artemis",
    "ConceptGraph": ".artemis",
    "ConceptNode": ".artemis",
    "SemanticTagger": ".artemis",
    "SemanticTag": ".artemis",
    "Citation": ".artemis",
    "BaseAgent": ".base_agent",
    "ArtemisAgent": ".artemis_agent",
    "LLMAgent": ".llm_agent",
    "ResearchAgent": ".research_agent",
    "SummarizerAgent": ".summarizer_agent",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_LAZY_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
