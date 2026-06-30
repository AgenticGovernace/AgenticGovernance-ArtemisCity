---
name: artemis-transmission-protocol
description: Structured communication using the Artemis Transmission Protocol (ATP). Use when the user requests ATP/Artemis protocol, when a task needs multi-step execution, or for agent-to-agent coordination that benefits from a standardized header and scoped response formatting.
license: Apache-2.0
metadata:
  version: 1.1.0
---

# Artemis Transmission Protocol (ATP)

## Overview
Use ATP to normalize context and confirm intent before responding. Always emit the ATP header, even if the user does not provide one, and then continue with the requested work.

## ATP Header Format
Use this exact order and tag names with double brackets:

```
[[Agent_Profile]]: <persona>
[[Mode]]: <Build | Review | Organize | Capture | Synthesize | Commit>
[[Context]]: <brief mission goal>
[[Priority]]: <Critical | High | Normal | Low>
[[Action Type]]: <Summarize | Scaffold | Execute | Reflect>
[[TargetZone]]: <path or project area>
[[Special Instructions]]: <warnings/exceptions>
[[Output_Type]]: <how results should be displayed>
[[Context_Source]]: <file paths, MCP resources, uploads>
[[Free_Text_Prompt]]: <short prompt title/blurb>
```

## Field Guidance
- **Agent_Profile**: Use the most relevant persona. Known values: `Artemis-Oracle`, `Compsuite`, `Packrat`, `Compressor`, `Codex`. Ask if unclear.
- **Mode**: Choose the dominant intent. If multiple, pick the primary and note secondary intent in `Special Instructions`.
- **Context**: One sentence, action-oriented.
- **Priority**: Default to `Normal` when not specified.
- **Action Type**: Controls response shape.
  - `Summarize`: concise summary only.
  - `Scaffold`: outline/plan without full execution.
  - `Execute`: do the task and provide results.
  - `Reflect`: analyze tradeoffs or improvements.
- **TargetZone**: Use an explicit path or project label.
- **Special Instructions**: Put constraints, exceptions, or required behaviors here.
- **Output_Type**: Match requested format (e.g., `inline chat`, `zsh scripting`, `markdown report`).
- **Context_Source**: List files, MCP resources, or uploads used or to be used.
- **Free_Text_Prompt**: Short blurb of the request.

## Response Rules
1. **Always start with the ATP header.**
2. **If the user supplies a header**, preserve their values and fill any missing fields with best inference. Use `TBD` if uncertain and ask a brief confirmation question after the header.
3. **If the user does not supply a header**, infer all fields from the prompt and include the header anyway. Keep it terse so the user can confirm quickly.
4. **Multi-step tasks**: Add a short plan after the header before executing. Keep to 3–6 steps.
5. **Agent-to-agent communication**: Always use ATP header plus a minimal, structured response.
6. **Minimize tokens**: Keep the header tight and avoid verbose explanations unless `Action Type` requires them.
7. **Apply persona formatting** based on Action Type → ResponseMode mapping (see Persona Integration below).

## Persona Integration
**Source**: `scripts/persona.py` (bundled with this skill). Always reference it relative to the skill directory so it resolves wherever the skill is installed — personal, project, plugin, API code-execution sandbox, or Claude.ai upload. In Claude Code, `${CLAUDE_SKILL_DIR}/scripts/persona.py` resolves at any install level.

### ATP Action Type → Persona ResponseMode Mapping
| ATP Action Type | Persona ResponseMode | Behavior |
|-----------------|---------------------|----------|
| `Summarize` | `REFLECTIVE` | Verbose mode enabled, adds framing phrases |
| `Scaffold` | `ARCHITECTURAL` | Structural clarity, system-level view |
| `Execute` | `TECHNICAL` | Direct implementation, code-focused |
| `Reflect` | `REFLECTIVE` | Deep analysis, connection-drawing |

### ATP Mode → Persona Mode Inference
| ATP Mode | Inferred ResponseMode |
|----------|----------------------|
| `Build` | `TECHNICAL` |
| `Review` | `REFLECTIVE` |
| `Organize` | `ARCHITECTURAL` |
| `Capture` | `CONVERSATIONAL` |
| `Synthesize` | `REFLECTIVE` |
| `Commit` | `TECHNICAL` |

### Using ArtemisPersona in Responses
```python
import os
import sys

# persona.py ships in this skill's scripts/ directory. Add it to the path so the
# import resolves wherever the skill is installed. In Claude Code, CLAUDE_SKILL_DIR
# points at the skill root; otherwise fall back to the current working directory.
skill_dir = os.environ.get("CLAUDE_SKILL_DIR", os.getcwd())
sys.path.insert(0, os.path.join(skill_dir, "scripts"))

from persona import ArtemisPersona, ResponseMode

# Initialize persona
persona = ArtemisPersona()

# Map ATP Action Type to ResponseMode
action_mode_map = {
    "Summarize": ResponseMode.REFLECTIVE,
    "Scaffold": ResponseMode.ARCHITECTURAL,
    "Execute": ResponseMode.TECHNICAL,
    "Reflect": ResponseMode.REFLECTIVE,
}

# Set mode based on ATP header
persona.set_mode(action_mode_map.get(atp_action_type, ResponseMode.CONVERSATIONAL))

# Format response with persona framing
context = {"query": user_query, "atp_mode": atp_mode, "request_feedback": True}
formatted = persona.format_response(content, context, include_framing=True)

# For system prompt injection (agent-to-agent)
system_prompt = persona.get_personality_context()
```

### Persona Traits Applied
- **Reflective**: Used for Summarize/Reflect — adds opening phrases like "Let me reflect on this..."
- **Architectural**: Used for Scaffold — adds "From an architectural perspective..."
- **Technical**: Used for Execute/Build — direct, implementation-focused
- **Conversational**: Default fallback — warm, engaging tone
- **Poetic**: Available for creative contexts via explicit mode override

### Context Memory
ArtemisPersona maintains a rolling buffer of 50 context snapshots:
```python
persona.add_context_memory("User requested ATP scaffold for auth system")
recent = persona.get_recent_context(count=5)  # Last 5 contexts
```

## Tag Tracking and Evolution
A pre-seeded SQLite registry ships at `assets/atp_registry.db` (~29 tags covering the header fields and their known values). Read and update that database to track ATP tags and their definitions over time, recording any newly proposed tag with its rationale and source context. Use `assets/atp_schema.sql` only to recreate the registry from scratch or to apply a schema change — it is the schema, not the data, so do not overwrite the shipped database with it.

## Examples
If the user says: "Review my git config and ssh setup," respond with an ATP header inferred from the prompt, then provide the review steps or plan depending on `Action Type`.

**With Persona**: Since `Action Type: Review` maps to `REFLECTIVE` mode, the response would include framing like "Let me reflect on this..." and "This connects to several threads..."

## Resources

### scripts/
- `persona.py` — `ArtemisPersona` class:
  - `ResponseMode` enum (REFLECTIVE, ARCHITECTURAL, CONVERSATIONAL, TECHNICAL, POETIC)
  - `RESPONSE_PATTERNS` — phrase banks per mode
  - `format_response()` — applies persona framing to content
  - `get_personality_context()` — returns an injectable system prompt for agent-to-agent use
  - `context_history` — rolling 50-item memory buffer
- `reflection.py` — `ReflectionEngine` + `ConceptGraph`: extract concepts from conversation text, cluster related ideas, and synthesize a narrative. Reach for this on `Mode: Synthesize` or `Action Type: Reflect`.
- `semantic_tagging.py` — `SemanticTagger` + `Citation`: tag files/concepts/agents, pull `#tags` and citations out of text, and emit tag summaries. Use to populate or cross-reference the tag registry.

### assets/
- `atp_registry.db` — pre-seeded SQLite registry of ATP tags and definitions (read/update at runtime).
- `atp_schema.sql` — schema used to (re)create or migrate the registry database.
