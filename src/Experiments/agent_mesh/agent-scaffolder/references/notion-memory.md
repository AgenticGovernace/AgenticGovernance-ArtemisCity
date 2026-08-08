# Notion Knowledgebase — memory & reflection backend

Goal: give a persistent agent its own Notion page so it can **write reflection write-ups**
there and **read them back as memory**, referencing the workspace structure as its
knowledge base. This is the recommended External-tier backend from SKILL.md step 2, and it
shares one source of truth with the ramble-on skill.

## The pattern: one agent ↔ one Notion page

- Each agent owns a Notion page (its "house"), ideally under a shared **Agents** root (or
  the existing Ramble On KB root).
- Structure on/under that page:
  - **Reflections** — dated write-ups appended over time (the Reflection layer's destination).
  - **Memory / Context** — durable state the agent reads on start (what it knows / decided).
  - **Audit** *(optional)* — action log, if not using a separate provenance store.
- "Reference through that structure" = the agent loads its page (and linked pages) for
  memory before acting, then writes its reflection back after.

## Routing — same graceful degradation as ramble-on

Mirror the ramble-on stack so the two share one build. Prefer tier 1; fall back as needed.

| Tier | Condition | Read memory | Write the reflection |
|------|-----------|-------------|----------------------|
| 1. Ramble server (app running) | `GET http://127.0.0.1:3748/health` ok | `ramble.kb_search` / `ramble.get_voice_model` | `ramble.kb_write` |
| 2. Notion MCP (no app) | Notion MCP connected | `notion-search` → `notion-fetch` | `notion-update-page` (insert_content) / `notion-create-pages` |
| 3. Files (neither) | fallback | read local log/state files | append to a local reflection log |

This is graceful degradation, not a hard dependency — the same three tiers ramble-on
defines.

## Exact Notion MCP calls (tier 2)

**Locate the agent's page**
- `notion-search` `{ "query": "<AgentName> agent reflection", "query_type": "internal", "page_size": 5 }`
  → take the page `id`. Once known, record the `page_id` in the agent's `AGENTS.md` so
  future runs skip the search.

**Load memory (read)**
- `notion-fetch` `{ "id": "<page_id_or_url>" }` → returns the page as Notion-flavored
  Markdown (Memory/Context + recent Reflections). Use it as the agent's startup context.

**Append a reflection write-up (write)**
- `notion-update-page` `{ "page_id": "<page_id>", "command": "insert_content", "position": {"type":"end"}, "content": "<write-up in Notion Markdown>" }`
- For a separate dated entry instead of inline append, use `notion-create-pages` with
  `parent {"type":"page_id","page_id":"<agent_or_Reflections_page>"}` and a titled page.

**Scaffold the agent's page once (first run)**
- `notion-create-pages` under the Agents root, with Memory / Reflections / Audit sections.

When composing `content`, follow Notion-flavored Markdown. Per the Notion MCP tool docs,
read the resource `notion://docs/enhanced-markdown-spec` before authoring rich content;
for reflections, plain headings + bullets are enough.

## Reflection write-up format (what gets written)

Keep each entry compact and skimmable:

```
## Reflection — <ISO date/time>  (run <id or seq>)
- Attempted: <one line>
- Assumptions: <any necessary assumptions, or "none">
- Drift check: <stayed within mission/boundaries? note exceptions>
- Events (audit agents): <rollup by severity since last summary>
- Next: <follow-ups, if any>
```

Trigger and cadence are set in the card (after major outputs; plus every N actions / T
hours for monitoring agents) — see `references/audit-reflection-persistence.md`.

## Optional: polish the write-up with ramble-on

A raw reflection is a "ramble." To store a clean, voice-preserving note, run it through the
**ramble-on** skill (Polished Note mode, or `ramble.translate` when the app is running)
before the write step. ramble-on already writes to the same Notion KB, so the loop stays
one source of truth.

## Build-stack note (for the ramble-server drop-in)

The ramble server is the local MCP app — a Tauri shell + Go server (replacing the earlier
Electron/Node `electron/mcp-server.cjs`; repo `AgenticGovernace/ramble_on`) — exposing
`ramble.*` tools on `http://127.0.0.1:3748`, backed by the Notion KB. agent-scaffolder uses
tier 2 (Notion MCP) today; when the Go ramble server is updated, agents route through tier
1 with **no card changes** — same KB, same page structure, fuller signal (voice model + KB
context). At that point, make `ramble.kb_write` / `ramble.kb_search` the preferred path and
keep the Notion MCP as the tier-2 fallback.

## Building the ramble server (mcp-builder)

The tier-1 server is itself an MCP server — build or extend it with the **mcp-builder**
skill. Keep the tool names stable so agent cards never change when the backend swaps in.

Minimum tool surface agent-scaffolder relies on:

- `ramble.kb_search(query)` → semantic search over the Notion KB (memory lookup).
- `ramble.kb_write(page, content)` → append a reflection write-up to the agent's Notion page.
- `ramble.get_voice_model()` → voice/config used when polishing write-ups.

(ramble-on additionally uses `ramble.translate`, `ramble.to_atp`, `ramble.to_platform_post`.)
Expose `GET /health` on `127.0.0.1:3748` so callers can detect tier 1 and fall back to the
Notion MCP when it's down. Build in Go per mcp-builder (stdio for local use, or streamable
HTTP); back every `ramble.*` tool with the same Notion KB so the three tiers stay one
source of truth.
