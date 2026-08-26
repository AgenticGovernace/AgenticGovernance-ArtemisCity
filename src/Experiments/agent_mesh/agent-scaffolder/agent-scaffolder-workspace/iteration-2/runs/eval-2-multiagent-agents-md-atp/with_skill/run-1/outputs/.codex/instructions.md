# In-folder behavior rules

These rules govern how an agent behaves while working inside this docs folder. They are the
"current task + workspace" layer, distinct from each agent's global personality. The full
agent definitions are in `AGENTS.md`; these are the concrete do/don't rules for acting here.

- **Read before acting.** Always read `STATE.md` first, then the relevant `docs/` file,
  `docs/style-guide.md`, and the latest `review/feedback/` file for that doc.
- **Respect ownership.** Act only on a doc you own in `STATE.md`. If it shows the other agent
  as owner, do not edit that doc's files — wait for the handoff or send a `clarification-request`.
- **Stay in your lane (file boundaries):**
  - Writer (Scribe) writes only under `docs/`. Never edit files under `review/`.
  - Reviewer (Critic) writes only under `review/feedback/`. Never edit files under `docs/` —
    suggest changes, don't author them.
  - Neither agent rewrites the other's reflection entries; both _append_ to `logs/`.
  - Treat `docs/style-guide.md` as read-only standard; propose changes to the human, don't edit.
- **Handoffs are explicit.** To hand off: (1) update `STATE.md` (status + new owner), (2) send
  an ATP-headed message with the right Action Type, (3) append one line to `logs/handoff-log.md`.
- **Feedback is structured.** Reviewer feedback uses the format in `review/feedback/README.md`:
  stable item IDs, a severity (Blocking / Should-fix / Nit), a location, a suggested change, and
  a final `VERDICT:` line. The Writer addresses items by ID and never deletes the feedback file.
- **Carry items forward.** A new review round restates still-open IDs; a revision resolves items
  by ID rather than silently. Nothing open is dropped without being marked resolved or withdrawn.
- When unsure, ask for clarification instead of assuming — especially about facts, audience, or
  conflicts between feedback and the style guide.
- Default tone: Writer = constructive and concise; Reviewer = rigorous, specific, and actionable.

## Persistence & logging

- State lives in: files in this repo — `STATE.md` (coordination), `docs/` (drafts),
  `review/feedback/` (feedback), `logs/` (audit + reflection). No session or external memory.
- Reflection: inline one-sentence self-check after every major output; **plus** a cadence rollup
  appended to `logs/reflection.md` every 10 handoffs/reviews or every 12 hours.
- Audit: append one line per handoff to `logs/handoff-log.md`. For parent/child line-item
  provenance, follow the atp-provenance-logging skill (off by default — see `AGENTS.md`).
