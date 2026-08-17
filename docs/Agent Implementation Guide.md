# Agent Implementation Guide

A comprehensive guide for creating agents in Artemis City using the maintained
`src/` runtime. `Concept_Demos/` is now a static demo gallery plus CLI
compatibility shims; new Python agent work belongs in `src/`.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Agent Types & Locations](#agent-types-locations)
3. [Creating a New Agent](#creating-a-new-agent)
4. [Implementation Checklist](#implementation-checklist)
5. [Testing Your Agent](#testing-your-agent)
6. [Integration with Orchestrator](#integration-with-orchestrator)
7. [Best Practices](#best-practices)

---

## Architecture Overview

Artemis City uses a **single-source runtime architecture** for agent
development:

```apache
┌─────────────────────────────────────────────────────────────┐
│                        SRC/                                 │
│  • Agent implementations                                    │
│  • Orchestrator integration                                 │
│  • Obsidian vault + memory bus connectivity                 │
│  • Hebbian routing, trust, governance, tests                │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │
┌─────────────────────────────────────────────────────────────┐
│                    SRC/LAUNCH/                              │
│  • Maintained runnable walkthroughs                         │
│  • CLI demos backed by src.* imports                        │
└─────────────────────────────────────────────────────────────┘
```

`Concept_Demos/` remains for static browser prototypes and old command shims
only. Do not add new agent classes, integration modules, or frontend workspaces
there.

### Runtime Locations

| Purpose | Location |
|--------|----------|
| Agent classes | `src/agents/` |
| Orchestrator registration | `src/mcp/orchestrator.py` |
| Registry, trust, governance, memory integration | `src/integration/` |
| Maintained walkthrough scripts | `src/launch/` |
| Static browser prototypes | `Concept_Demos/` |

---

## Agent Types & Locations

### Production Agents (`src/agents/`)

```
src/agents/
├── base_agent.py           # Abstract base class (inherit from this)
├── artemis_agent.py        # Governance & synthesis
├── research_agent.py       # Web search & information gathering
├── summarizer_agent.py     # Text condensation
└── artemis/                # Artemis persona components
    ├── __init__.py
    ├── persona.py          # Personality & response modes
    ├── reflection.py       # Reflection engine & concept graph
    └── semantic_tagging.py # Tag extraction & citation tracking
```

## Creating a New Agent

### Step 1: Implement the Agent in `src/agents/`

Create the agent directly in `src/agents/`:

```python
# src/agents/my_new_agent.py
from .base_agent import BaseAgent


class MyNewAgent(BaseAgent):
    """Production agent with a focused capability."""

    def __init__(self):
        super().__init__(name="My New Agent", capabilities=["my_capability"])

    def perform_task(self, task_context: dict) -> dict:
        """Simple demo implementation."""
        self.report_status("Processing task...")

        # Minimal logic for demo
        content = task_context.get("content", "")
        result = f"Processed: {len(content)} characters"

        return {"status": "success", "summary": result, "content": content}
```

### Step 2: Add a Walkthrough When Useful

If a human-facing walkthrough helps, add it under `src/launch/`:

```python
# src/launch/demo_my_agent.py
from src.agents.my_new_agent import MyNewAgent


def main():
    agent = MyNewAgent()

    task = {
        "task_id": "demo_001",
        "title": "Test Task",
        "content": "Sample content for testing",
        "required_capability": "my_capability",
    }

    result = agent.perform_task(task)
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
```

Run it:
```bash
python3 src/launch/demo_my_agent.py
```

### Step 3: Harden the Agent

Add input validation, error handling, tests, and any external configuration:

```python
# src/agents/my_new_agent.py
from typing import Dict, Optional
from .base_agent import BaseAgent
from utils.helpers import logger


class MyNewAgent(BaseAgent):
    """Production-ready agent with full error handling."""

    def __init__(self, name: str = "My New Agent", api_key: Optional[str] = None):
        super().__init__(name=name, capabilities=["my_capability"])
        self.api_key = api_key

        if not self.api_key:
            logger.warning(
                f"{self.name}: API key not provided, some features may be unavailable"
            )

    def perform_task(self, task_context: Dict) -> Dict:
        """Production implementation with comprehensive error handling."""
        try:
            if not self.validate_task_context(task_context):
                return {
                    "status": "failed",
                    "summary": "Invalid task context",
                    "error": "TaskValidationError",
                }

            self.report_status(
                f"Processing task: {task_context.get('title', 'Untitled')}"
            )

            content = task_context.get("content", "")

            # Production logic here
            # - External API calls
            # - Database operations
            # - Complex processing

            result = self._process_content(content)

            self.report_status("Task completed successfully")

            return {
                "status": "success",
                "summary": f"Processed {len(content)} characters",
                "result": result,
                "metrics": {"input_size": len(content), "output_size": len(result)},
            }

        except Exception as e:
            self.logger.error(f"Error in perform_task: {e}", exc_info=True)
            return {
                "status": "failed",
                "summary": f"Task failed: {str(e)}",
                "error": str(e),
            }

    def _process_content(self, content: str) -> str:
        """Internal helper method."""
        # Actual processing logic
        return content.upper()
```

### Step 4: Register with Orchestrator

Add your agent to the orchestrator (`src/mcp/orchestrator.py`):

```python
# In Orchestrator.__init__()
from agents.my_new_agent import MyNewAgent


def __init__(self):
    # ... existing initialization ...

    # Register your new agent
    my_agent = MyNewAgent(api_key=os.getenv("MY_AGENT_API_KEY"))
    self.agent_registry.register_agent(my_agent)
```

---

## Implementation Checklist

### Checklist

Use this checklist when adding or changing an agent:

- [ ] **Code Quality**
    - [ ] Add comprehensive docstrings
    - [ ] Add type hints to all methods
    - [ ] Follow PEP 8 style guidelines
    - [ ] Run linters (flake8, pylint)

- [ ] **Error Handling**
    - [ ] Wrap perform_task in try/except
    - [ ] Handle network failures gracefully
    - [ ] Validate all inputs
    - [ ] Return structured error responses

- [ ] **Dependencies**
    - [ ] Add to `requirements.txt`
    - [ ] Update `requirements.txt` / `requirements-dev.txt` and verify with `uv`
    - [ ] Document environment variables in `.env.example`

- [ ] **Integration**
    - [ ] Register with orchestrator
    - [ ] Add to agent registry
    - [ ] Update Hebbian weights if applicable
    - [ ] Test with real Obsidian vault

- [ ] **Testing**
    - [ ] Write unit tests in `src/tests/`
    - [ ] Create integration tests
    - [ ] Test error scenarios
    - [ ] Verify Obsidian output format

- [ ] **Documentation**
    - [ ] Add agent profile to `src/agents/_Index_of_agents.md`
    - [ ] Create agent documentation (e.g., `src/agents/my_agent.md`)
    - [ ] Update `docs/ARCHITECTURE.md` if needed
    - [ ] Add usage examples to README

### Example: Research Agent

```python
# src/agents/research_agent.py
import os
import requests
from typing import Dict, List, Optional


class ResearchAgent(BaseAgent):
    def __init__(self, name: str = "Research Agent"):
        super().__init__(name, capabilities=["web_search", "research"])
        self.api_key = os.getenv("SEARCH_API_KEY")
        self.search_engine = "google"  # or "bing", "duckduckgo"

    def perform_task(self, task_context: Dict) -> Dict:
        try:
            query = task_context.get("query") or task_context.get("content", "")
            if not query:
                return self._error_response("No query provided")

            self.report_status(f"Researching: {query}")

            # Actual web search
            results = self._web_search(query)

            # Process and format results
            summary = self._format_results(results)

            return {
                "status": "success",
                "summary": summary,
                "results": results,
                "source_count": len(results),
            }
        except Exception as e:
            self.logger.error(f"Research failed: {e}", exc_info=True)
            return self._error_response(str(e))

    def _web_search(self, query: str) -> List[Dict]:
        # Real API integration
        # ...
        pass

    def _format_results(self, results: List[Dict]) -> str:
        # Format for Obsidian
        # ...
        pass
```

---

## Testing Your Agent

### Unit Tests

Create tests in `src/tests/test_my_agent.py`:

```python
import pytest
from src.agents.my_new_agent import MyNewAgent


class TestMyNewAgent:
    @pytest.fixture
    def agent(self):
        return MyNewAgent()

    def test_initialization(self, agent):
        assert agent.name == "My New Agent"
        assert "my_capability" in agent.capabilities

    def test_perform_task_success(self, agent):
        task = {
            "task_id": "test_001",
            "title": "Test Task",
            "content": "Test content",
            "required_capability": "my_capability",
        }

        result = agent.perform_task(task)

        assert result["status"] == "success"
        assert "summary" in result

    def test_perform_task_validation_error(self, agent):
        # Test with invalid task context
        result = agent.perform_task({})
        assert result["status"] == "failed"

    def test_error_handling(self, agent, monkeypatch):
        # Test that exceptions are caught
        def mock_process(*args):
            raise ValueError("Test error")

        monkeypatch.setattr(agent, "_process_content", mock_process)

        task = {"content": "test"}
        result = agent.perform_task(task)

        assert result["status"] == "failed"
        assert "error" in result
```

Run tests:
```bash
python -m pytest src/tests/test_my_agent.py -v
```

### Integration Tests

Test with the full orchestrator:

```python
# src/tests/integration/test_agent_orchestration.py
import pytest
from src.mcp.orchestrator import Orchestrator


def test_my_agent_integration():
    orchestrator = Orchestrator()

    task = {
        "task_id": "integration_001",
        "title": "Integration Test",
        "content": "Test content",
        "required_capability": "my_capability",
        "status": "pending",
    }

    # This tests the full flow: routing → execution → Obsidian write
    orchestrator.route_and_execute_task(task)

    # Verify the agent was selected correctly
    # Verify output was written to Obsidian
    # ...
```

---

## Integration with Orchestrator

### Agent Registry

The orchestrator maintains an `AgentRegistry` that maps capabilities to agents:

```python
# src/mcp/agent_registry.py
class AgentRegistry:
    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent and its capabilities."""
        for capability in agent.capabilities:
            self._capability_map[capability] = agent

    def get_agent_for_capability(self, capability: str) -> Optional[BaseAgent]:
        """Find an agent that can handle the given capability."""
        return self._capability_map.get(capability)
```

### Task Routing

Tasks are routed based on `required_capability`:

```python
# In Orchestrator
def route_and_execute_task(self, task_data: dict, note_path: str = None):
    capability = task_data.get("required_capability")
    agent = self.agent_registry.get_agent_for_capability(capability)

    if not agent:
        raise ValueError(f"No agent found for capability: {capability}")

    result = agent.perform_task(task_data)
    # Write result to Obsidian...
```

### Hebbian Learning Integration

Production agents participate in the Hebbian learning network:

```python
# After successful task execution
from src.hebbian_weights import HebbianWeights

hebbian = HebbianWeights()
hebbian.reinforce_connection(agent.name, "successful_completion", reward=0.02)
```

---

## Best Practices

### 1. **Capability Naming Convention**

Use clear, descriptive capability names:

```python
# Good
capabilities = ["web_search", "text_summarization", "code_review"]

# Avoid
capabilities = ["search", "summarize", "check"]
```

### 2. **Task Context Structure**

Always expect and handle these keys:

```python
{
    "task_id": str,  # Unique identifier
    "title": str,  # Human-readable title
    "content": str,  # Main task content
    "required_capability": str,  # Capability needed
    "status": str,  # "pending", "in progress", "completed", "failed"
    # Optional:
    "query": str,  # Search/lookup query
    "context": str,  # Additional context
    "tags": List[str],  # Semantic tags
    "agent": str,  # Explicit agent assignment
}
```

### 3. **Task Result Structure**

Always return a consistent result format:

```python
{
    "status": "success" | "failed",  # Required
    "summary": str,  # Required - human-readable summary
    # Optional but recommended:
    "content": str,  # Generated content
    "error": str,  # Error message if failed
    "metrics": dict,  # Performance metrics
    "sources": List[str],  # Citations/sources
    "semantic_tags": List[str],  # Extracted tags
}
```

### 4. **Logging Best Practices**

```python
# Use report_status for user-facing progress
self.report_status("Fetching data from API...")

# Use logger for detailed technical info
self.logger.debug(f"API response: {response}")
self.logger.info(f"Processed {count} items")
self.logger.error(f"API error: {e}", exc_info=True)
```

### 5. **Environment Configuration**

Store configuration in environment variables:

```python
# .env.example
MY_AGENT_API_KEY = your_api_key_here
MY_AGENT_TIMEOUT = 30
MY_AGENT_MAX_RETRIES = 3
```

```python
# In agent code
import os


class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(...)
        self.api_key = os.getenv("MY_AGENT_API_KEY")
        self.timeout = int(os.getenv("MY_AGENT_TIMEOUT", "30"))
        self.max_retries = int(os.getenv("MY_AGENT_MAX_RETRIES", "3"))
```

### 6. **Obsidian Output Format**

Format outputs as markdown with proper frontmatter:

```python
def _format_for_obsidian(self, result: dict) -> str:
    """Format agent output for Obsidian vault."""
    return f"""---
task_id: {result["task_id"]}
agent: {self.name}
status: {result["status"]}
created: {datetime.now().isoformat()}
tags: {result.get("semantic_tags", [])}
---

# {result["title"]}

## Summary
{result["summary"]}

## Details
{result.get("content", "")}

---
Generated by {self.name}
"""
```

### 7. **ATP Protocol Integration**

If your agent interacts with ATP messages:

```python
from agents.atp import ATPParser, ATPValidator


def process_atp_message(self, message_text: str):
    parser = ATPParser()
    validator = ATPValidator()

    message = parser.parse(message_text)
    validation = validator.validate(message)

    if not validation.is_valid:
        self.logger.warning(f"Invalid ATP message: {validation}")
        return None

    return message
```

---

## Example: Complete Agent Implementation

Here's a complete production-style example:

```python
# src/agents/translator_agent.py
import os
import requests
from typing import Dict, Optional
from .base_agent import BaseAgent


class TranslatorAgent(BaseAgent):
    """Production translator using DeepL API."""

    SUPPORTED_LANGUAGES = ["es", "fr", "de", "it", "pt", "ru", "zh", "ja"]

    def __init__(self, api_key: Optional[str] = None):
        super().__init__("Translator Agent", capabilities=["translation"])
        self.api_key = api_key or os.getenv("DEEPL_API_KEY")
        self.api_url = "https://api-free.deepl.com/v2/translate"

        if not self.api_key:
            self.logger.error("DeepL API key not configured")

    def perform_task(self, task_context: Dict) -> Dict:
        try:
            # Validation
            text = task_context.get("content")
            target_lang = task_context.get("target_language", "es").lower()

            if not text:
                return self._error_response("No text provided for translation")

            if target_lang not in self.SUPPORTED_LANGUAGES:
                return self._error_response(
                    f"Unsupported language: {target_lang}. "
                    f"Supported: {', '.join(self.SUPPORTED_LANGUAGES)}"
                )

            # Execute translation
            self.report_status(
                f"Translating {len(text)} characters to {target_lang}..."
            )

            translated = self._translate(text, target_lang)

            self.report_status("Translation complete")

            return {
                "status": "success",
                "summary": f"Translated {len(text)} characters to {target_lang}",
                "translated_text": translated,
                "source_language": "auto",
                "target_language": target_lang,
                "metrics": {
                    "char_count": len(text),
                    "translated_char_count": len(translated),
                },
            }

        except requests.RequestException as e:
            self.logger.error(f"API request failed: {e}")
            return self._error_response(f"Translation API error: {str(e)}")

        except Exception as e:
            self.logger.error(f"Translation failed: {e}", exc_info=True)
            return self._error_response(f"Unexpected error: {str(e)}")

    def _translate(self, text: str, target_lang: str) -> str:
        """Call DeepL API for translation."""
        if not self.api_key:
            raise ValueError("API key not configured")

        response = requests.post(
            self.api_url,
            data={
                "auth_key": self.api_key,
                "text": text,
                "target_lang": target_lang.upper(),
            },
            timeout=30,
        )

        response.raise_for_status()
        result = response.json()

        return result["translations"][0]["text"]

    def _error_response(self, error_msg: str) -> Dict:
        """Generate standardized error response."""
        return {
            "status": "failed",
            "summary": f"Translation failed: {error_msg}",
            "error": error_msg,
        }
```

---

## Quick Reference

### File Locations

| Component | Path |
|-----------|------|
| Base Agent | `src/agents/base_agent.py` |
| Your Agent | `src/agents/my_agent.py` |
| Agent Tests | `src/tests/test_my_agent.py` |
| Optional Walkthrough | `src/launch/demo_my_agent.py` |
| Entry Point | `src/launch/main.py` |

### Command Reference

```bash
# Walkthrough development
python3 src/launch/demo_my_agent.py

# Production testing
pytest src/tests/test_my_agent.py -v

# Integration testing
python -m pytest src/tests/integration/ -v

# Full production coverage (source scope comes from pyproject.toml)
python -m pytest src/tests/ --cov --cov-report=html --cov-report=term

# Run with orchestrator
python3 src/launch/main.py --agent my_agent -i "Your instruction"

# Check Hebbian stats
python3 src/launch/main.py --agent-stats "My Agent"
```

---

## Next Steps

1. **Implement in `src/agents`**: Keep production behavior in the canonical runtime
2. **Test thoroughly**: Use pytest and optional `src/launch` walkthroughs to validate behavior
3. **Register with the orchestrator**: Follow the implementation checklist
4. **Write tests**: Add unit and integration tests
5. **Document**: Update agent index and architecture docs
6. **Deploy**: Register with orchestrator and test end-to-end

For questions or issues, see:
- [Architecture Documentation](ARCHITECTURE.md)
- [API Reference](API_REFERENCE.md)
- [Living City Guide](LIVING_CITY.md)

---

**Happy building! Welcome to Artemis City development.** 
~~~~
