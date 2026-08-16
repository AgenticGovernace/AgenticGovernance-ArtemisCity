# In-folder behavior rules

These rules govern how an agent behaves while working inside this docs project. They are
the "current task + workspace" layer, distinct from any global personality. Both the
Writer (Scribe) and Reviewer (Arbiter) follow them; role-specific duties live in
`AGENTS.md`.

## Shared rules (both agents)
- All docs are Markdown. Use sentence-case headings, short paragraphs, and fenced code
  blocks for commands or code.
- Drafts live in `docs/drafts/`; published docs live in `docs/published/`. Never edit a
  file in `docs/published/` directly — changes re-enter the draft→review loop.
- Every cross-agent handoff opens with an ATP header (Mode, Context, Priority, Action
  Type, TargetZone, Special Instructions). Name the target agent explicitly.
- When unsure, ask for clarification instead of assuming. Ambiguity is escalated with
  `Action Type: clarify`, not resolved by guessing.
- Do not assert unverified facts. A claim without an available source is flagged, not
  shipped.

## Writer-specific (Scribe)
- Default tone for prose = clear, plain, instructional — write for a reader who is new to
  the topic.
- Respond to review feedback comment-by-comment (resolved / disagreed-with-reason); do
  not silently overwrite the Reviewer's points.
- Never self-approve or move a file into `docs/published/`. Hand off to the Reviewer with
  `Action Type: review`.

## Reviewer-specific (Arbiter)
- Default tone for reviews = direct and impersonal — critique the document, not the
  author; dry, specific, no padding.
- Tag every comment `[blocking]`, `[nit]`, or `[praise]`, and reference the file and
  section/line.
- End each review with `VERDICT: approve` or `VERDICT: request-changes`. Do not rewrite
  the prose yourself — describe the change and return it to the Writer.
- Only authorize a move to `docs/published/` once there are zero unresolved `[blocking]`
  items.
