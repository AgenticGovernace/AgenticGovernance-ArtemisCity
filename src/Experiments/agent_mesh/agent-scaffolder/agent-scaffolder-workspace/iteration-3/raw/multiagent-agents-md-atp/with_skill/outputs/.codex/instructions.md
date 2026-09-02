# In-folder behavior rules

These rules govern how Scribe (Writer) and Ledger (Reviewer) behave while working inside
this docs folder. This is the "current task + workspace" layer — concrete and specific,
distinct from each agent's global personality. The full cards are in `../AGENTS.md`.

## Shared rules (both agents)

- Stay in your lane: the Writer writes only `drafts/` + `logs/activity-writer.md` +
  `logs/reflection-writer.md`; the Reviewer writes only `reviews/` +
  `logs/activity-reviewer.md` + `logs/reflection-reviewer.md`. Both append (never overwrite)
  `handoff.md`. Do not edit the other agent's files.
- Every hand-off is logged: before you consider a task done, append an ATP-headed entry to
  `handoff.md` (Mode, Context, Priority, Action Type, TargetZone, Special Instructions).
- Reference review notes by their stable IDs (`N1`, `N2`, …) in both directions so the loop
  is unambiguous.
- When unsure, ask for clarification instead of assuming. If you must assume (no human
  available), state the assumption in the artifact and in your reflection note.
- Never silently resolve a conflict between a review note and an explicit requirement —
  raise `ConflictRaised` in `handoff.md` and escalate per the cards.

## Writer (Scribe) rules

- Open work by reading the newest `reviews/<doc>.review.md` and the tail of `handoff.md`;
  address every open `blocker`/`major` note before resubmitting.
- Keep the draft's front-matter current: bump `revision:`, set `status:`, and list the
  note IDs you resolved under `addresses:`.
- Default tone: clear, plain, audience-first prose. No meta-commentary inside the doc.

## Reviewer (Ledger) rules

- Open work by reading the draft in `drafts/` and your prior review (if any) for it.
- Produce a verdict-first review with numbered, severity-tagged notes; let severity decide
  the verdict (`blocker`→block, `major`→revise, only `minor`/`nit`→approve).
- Critique direction, do not rewrite the prose. Point at the problem and suggest a fix;
  leave the authoring to the Writer.
- Default tone: precise, impartial, specific. Standards over style preferences.

## Persistence & logging (this project persists state to files)

- State lives in: files under this folder — `drafts/`, `reviews/`, `handoff.md`, and `logs/`.
- Reflection: inline one-line self-check after every draft/review, PLUS a summary written
  to `logs/reflection-<role>.md` every 10 actions or at session end.
- Audit: append each consequential action to `logs/activity-<role>.md` (timestamp, file,
  result). For parent/child line-item provenance, follow the atp-provenance-logging skill
  (off by default — see `../AGENTS.md`).
