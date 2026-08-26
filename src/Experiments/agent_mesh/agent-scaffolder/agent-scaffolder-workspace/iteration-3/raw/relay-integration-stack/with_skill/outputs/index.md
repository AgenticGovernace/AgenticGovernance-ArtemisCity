# Relay — task hand-off agent (ramble stack)

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is

This folder defines **Relay**, the task-routing agent for the **ramble stack**. Relay
accepts incoming tasks and hands them off to other agents over the Artemis Transmission
Protocol (ATP). It does not do the downstream work itself — it frames, routes, tracks,
and reconciles hand-offs. Its memory and reflections live on its own Notion page (so they
survive across sessions), and every action it takes is logged for audit.

## What's here

- `AGENTS.md` — Relay's Agent Card: role, mission, boundaries, escalation, the
  External-tier persistence model (Notion KB + provenance store), the ATP communication
  layer, and the audit/provenance contract. **Start here.**
- `.codex/instructions.md` — concrete behavioral rules for acting _inside this folder_
  (how to form an ATP hand-off, when to read/write Notion, the halt-on-log-failure rule).
- `logs/` — the offline mirror and tier-3 fallback destination: local reflection log and
  per-action audit log used only when the Notion KB and provenance service are
  unreachable. See `logs/README.md`.

## How to use it

1. **On startup, load memory first.** Read Relay's Notion page (tier 1: `ramble.kb_search`
   when the ramble app is running; tier 2: Notion MCP `notion-search` → `notion-fetch`;
   tier 3: `logs/`) before routing anything. Record the resolved `page_id` in `AGENTS.md`
   so future runs skip the lookup.
2. **Route over ATP.** Every hand-off opens with a full ATP header and carries the
   prompt's parent `prov_id`. Honor the symmetric ack/decline handshake.
3. **Log every action, then reflect.** Each action is a provenance line item
   (`agent_logs` via `$PROVENANCE_SERVICE_URL`); halt-and-alert if a log write fails.
   After each hand-off, append a reflection write-up to the Notion page.

## Stack context

Relay is one piece of the ramble stack, which shares one source of truth:

- **agent-scaffolder** defined this agent.
- **artemis-transmission-protocol** carries the hand-off messages between agents.
- The **Notion KB** (via the ramble server, falling back to the Notion MCP) holds Relay's
  memory and reflections.
- **atp-provenance-logging** records every action with parent/child `prov_id`s.
- **ramble-on** can polish a raw reflection before it lands in Notion.
- **mcp-builder** builds/extends the ramble server that backs tier-1 routing.
