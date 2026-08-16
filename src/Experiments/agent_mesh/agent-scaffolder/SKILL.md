---
name: agent-scaffolder
description: >-
  Scaffold AI agents using the Agent Card (Role, Mission, Output Standards, Escalation, Memory, Reflection, Audit) to generate system prompts and create index.md, AGENTS.md, .codex/instructions.md—trigger on setup, definition, AGENTS.md edits, prompts, personas, audit/monitoring agents, reflection/self-checks, memory/logging, or multi-agent projects. Gate Memory/Reflection/Audit on runtime persistence. Use artemis-transmission-protocol for agent communication and atp-provenance-logging for action provenance (halt on logging failure). Persist memory/reflection via Notion (ramble server or Notion MCP; see references/notion-memory.md).
---

# Agent Scaffolder

## What this does

Turn a rough idea of an agent ("a CLI refactor bot," "a directory-watching audit agent")
into two concrete things:

1. **An Agent Card** — a complete system prompt built from a layered formula.
2. **A folder scaffold** — the files that give an agent durable, location-aware
   context: `index.md`, `AGENTS.md`, and `.codex/instructions.md`.

It also decides, *explicitly*, how much the agent can **remember, reflect on, and
audit** — and gates those layers on what the runtime actually persists. The premise:
consistent behavior comes from scoped, file-based instructions next to the work, not
from global memory; and memory, reflection, and audit only mean anything if there is
somewhere to keep them.

## When to use

- "Set up / define / scaffold an agent for X"
- "Write me an AGENTS.md / system prompt / persona / behavior spec for X"
- "Design an audit or monitoring agent" / "have it watch a folder and log activity"
- "How should this agent reflect / self-check / summarize its work?"
- "What should this agent remember or log?"
- Organizing a multi-agent project where each area needs its own behavior

Hand-offs to sibling skills (the stack this skill plugs into):

- **Agent-to-agent communication** (session headers, signal tags, symmetric
  ack/decline, fault-awareness): use the **artemis-transmission-protocol** skill.
- **Line-item action provenance** (one parent `prov_id` per prompt, a child entry per
  read/write/execute/tool-call in `agent_logs`, halt-and-alert if logging fails): use
  the **atp-provenance-logging** skill.
- **Persistent memory & reflection** (the agent writes reflection write-ups to its own
  Notion page and reads them back): see `references/notion-memory.md` — Notion MCP today,
  the ramble server as tier-1 when the app is running.
- **Polishing a reflection write-up** (raw → clean, voice-preserving note before it lands
  in Notion): use the **ramble-on** skill.
- **Building or extending the ramble server** (the local MCP, Go, that backs tier-1 Notion
  routing): use the **mcp-builder** skill — it must expose the `ramble.*` tool surface
  documented in `references/notion-memory.md`.

How it ties together: **agent-scaffolder** defines the agent; **ATP** carries messages
between agents; the **Notion KB** (via the ramble server / Notion MCP) holds memory and
reflections; **atp-provenance-logging** records every action; **ramble-on** polishes the
write-ups; **mcp-builder** builds the server that makes tier-1 routing real. One stack,
one source of truth.

## Workflow

### 1. Gather just enough

Collect only what's needed to fill the formula. Ask for what's missing; infer sensible
defaults and state them.

- **Role + attitude** — name and voice.
- **Mission** — the task set it owns, plus explicit non-goals / boundaries.
- **Output standards** — default format and verbosity.
- **Escalation** — what to do when ambiguous, out of scope, or above a severity threshold.
- **Persistence model** — *where, if anywhere, does this agent's state live?* (See step 2.)
- **Location** — which folder or repo this agent governs.

### 2. Set the persistence model — this gates Memory, Reflection logging, and Audit

Before filling the optional layers, decide where state lives. This is the single most
important call, because it determines which layers are real and which would be theater.

| Persistence model | What it means | Memory layer | Reflection | Audit / Provenance |
|---|---|---|---|---|
| **Ephemeral** (default) | one turn/session; nothing survives | omit | inline one-line self-check only | omit |
| **Session** | state held for the live session only | recall within the session | summarize at session end | optional, in-session notes |
| **File-based** | reads/writes files (logs, `index.md`, `.csv`/`.qmd`) | read prior log/state files | append summaries to a reflection log on a cadence | write action log files; escalate via a high-priority log |
| **External service / DB** | a provenance service or database | backed by the store | logged as entries | use **atp-provenance-logging** (parent + child `prov_id`s) |

**Key principle:** never write a Memory, Reflection-cadence, or Audit instruction the
runtime can't honor. An "every 50 actions, summarize and recall prior state" rule on an
agent with no persistence trains it to *narrate* continuity it doesn't have — the
"hallucinated persistence" failure. Match the layer to the tier, and say which tier you
chose and why.

**Notion knowledgebase — the recommended persistent backend.** When an agent should
remember and reflect across sessions, give it its own Notion page: it writes reflection
write-ups there and reads them back as memory, referencing the workspace structure as its
knowledge base. This routes through the ramble server's local MCP when the app is running,
falls back to the Notion MCP directly, then to file logs — the same graceful-degradation
stack the ramble-on skill uses. See `references/notion-memory.md` for the page structure
and the exact tool calls.

### 3. Generate the Agent Card

Fill the layers below. Layers marked *gated* are included only when step 2's tier
supports them — otherwise omit them rather than leave empty ceremony.

| Layer | Purpose | Persistence-gated? |
|-------|---------|--------------------|
| Role | Who the agent is + attitude | no |
| Mission | Tasks it owns + prohibited tasks/boundaries | no |
| Output Standards | Format, verbosity, assumptions | no |
| Escalation Rules | Ambiguity / out-of-scope / severity threshold | no |
| Memory / Context | What to recall, and from where | **yes** — needs session/file/service |
| Reflection | Self-check + cadence summaries | **partly** — inline always; cadence needs persistence |
| Audit / Provenance *(opt)* | Log actions for trace and review | **yes** — needs a log destination |
| Version *(meta)* | Track changes over time (v1.0, v1.1…) | no |

Two card shapes:

- **Lean task agent** → `assets/agent-card.template.md` (the six core layers).
- **Audit / monitoring / long-running agent** → `assets/audit-agent-card.template.md`
  (adds Purpose, Boundaries, Escalation Policy, Reflection Routine, Audit & Provenance,
  Version, Behavioral Notes).

### 4. Reflection — make it real

Reflection is a self-check, not decoration. Define it on three axes:

- **Trigger** — *after every major output* (always, even for ephemeral agents: a
  one-sentence self-check). For persistent agents, *also* on a cadence: every N actions
  (e.g., 50) or every T hours (e.g., 12), mirroring an audit agent's summary routine.
- **Content** — what was attempted, whether assumptions were necessary, and whether
  anything drifted from the mission or boundaries. For audit agents, a rollup of events
  by severity.
- **Destination** — ephemeral → inline in the response; persistent → appended to a
  reflection/summary log (and, with provenance, recorded as a line item). With a Notion
  knowledgebase, the write-up is appended to the agent's Notion page via the ramble server
  or Notion MCP (see `references/notion-memory.md`); optionally polish the raw reflection
  into a clean note with the ramble-on skill before writing.

The cadence only earns its place when there's a destination to write to — otherwise drop
it and keep the inline self-check.

### 5. Audit & provenance

Add the Audit layer when the agent takes consequential actions you need to trace, runs
unattended or long, or coordinates with other agents.

- **Observe-and-log archetype:** monitoring agents observe and log but **never modify** —
  encode that as a hard boundary (e.g., "DO NOT edit, delete, or modify files; observe
  and log only").
- **What to log:** each action (read / write / execute / tool call) with input, output,
  and status; plus an escalation threshold (e.g., escalate only above `Warning`).
- **Rigorous line-item provenance:** when the user wants every action traceable with a
  parent prompt ID and linked child IDs, follow the **atp-provenance-logging** skill and
  reference it from `AGENTS.md`. Note it expects a reachable provenance service and
  *halts the agent if a log write fails* — only wire it in when that strictness is wanted.

For the full playbook (persistence tiers in depth, reflection patterns, the provenance
hand-off, and a worked audit-agent example), read
`references/audit-reflection-persistence.md`.

### 6. Lay down the folder scaffold

Create these in the target folder using the templates in `assets/`:

- **`index.md`** — a README *for the agent*: what this location is, what lives here, how
  to use it.
- **`AGENTS.md`** — the Agent Card, plus pointers to the ATP comms layer and/or the
  provenance skill when the project needs them.
- **`.codex/instructions.md`** — concrete behavioral rules for acting *inside this folder*.
- When the persistence model is file-based, also create the **log destination** the card
  references (e.g., a `logs/` directory).

### 7. Explain the scope model (when relevant)

Instruction scope cascades from broad to specific — global/personal defaults are
overridden by project-wide rules, which are overridden by the local folder's files:

```
global defaults  <  project-wide rules  <  this folder's index.md / instructions.md
```

Treat global memory as the *personality* layer and the folder files as the *current-task*
layer. Whether a tool auto-loads these files varies by runtime — verify rather than assume.

## Output

By default, write real files into the target folder. State which persistence tier you
chose and why, and which optional layers you included or omitted as a result. If the user
only wants the prompt, output just the Agent Card. Always tell the user what you created
and where.

## Templates & references

- `assets/agent-card.template.md` — lean six-layer card
- `assets/audit-agent-card.template.md` — expanded monitoring / audit card
- `assets/index.md.template` — folder context README
- `assets/AGENTS.md.template` — agent definition + ATP and provenance pointers
- `assets/codex-instructions.md.template` — in-folder behavior rules
- `references/audit-reflection-persistence.md` — persistence tiers, reflection patterns,
  provenance integration, and a worked audit-agent example
- `references/notion-memory.md` — Notion-knowledgebase backend for memory & reflection
  (agent ↔ Notion page, MCP routing, exact tool calls, ramble-server drop-in)
