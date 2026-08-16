# index.md — relay-integration-stack

> Folder README. Gives any agent (or human) entering this directory the context for
> where they are and what lives here.

## What this folder is

This is the home of **Relay**, the task-handoff dispatcher of the **ramble stack**.
Relay's one job is to take an incoming task, decide which downstream agent should own it,
and hand it off over the **Artemis Transmission Protocol (ATP)** — while persisting its
reflections to a Notion page so they survive across sessions, and logging every action
to an append-only audit trail.

If you are an agent that just entered this folder: read [`.codex/instructions.md`](.codex/instructions.md)
for how to behave here, then read [`AGENTS.md`](AGENTS.md) for the full Relay contract.

## What lives here

| Path | What it is |
|------|------------|
| `AGENTS.md` | **Read first.** Relay's Agent Card + the coordination/handoff contract. |
| `relay/system-prompt.md` | The full Relay system prompt (paste into the model). |
| `relay/agent.py` | Reference runtime: the dispatcher loop. |
| `relay/atp.py` | ATP transmission build/parse + ack matching. |
| `relay/audit.py` | Append-only audit logger (halts on write failure). |
| `relay/memory.py` | Notion-backed reflection store with a local mirror fallback. |
| `relay/registry.json` | The downstream agents Relay may hand off to. |
| `relay/relay.config.json` | Runtime config: ATP version, Notion page id, timeouts. |
| `ATP_PROTOCOL.md` | The ATP contract shared by Relay and its partner agents. |
| `handoffs/outbox/` | ATP transmissions Relay has sent (one `.atp` file per `ctx`). |
| `handoffs/inbox/` | Acks/replies received, matched back by `ctx` hash. |
| `logs/actions.log.jsonl` | The audit trail — every action, append-only, one JSON per line. |
| `reflections/local-mirror.md` | Offline mirror of the Notion reflections page. |

## The three things Relay guarantees

1. **Handoff over ATP** — no freeform delegation; every task leaves as a well-formed
   ATP transmission with a `ctx` hash and an expected ack tag.
2. **Persistent reflection** — reflections are written to the Notion page
   *"Relay — Reflections"*, so Relay resumes with its memory intact each session.
3. **Full audit** — every action is logged before it counts as done; an unwritable log
   halts the action.

## Run it

```bash
# from this folder
python -m relay          # starts Relay's dispatcher loop
```

Relay is one component of the **ramble stack**; it coordinates with the other agents
registered in `relay/registry.json`.
