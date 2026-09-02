# AGENTS.md

> Coordination contract for the **Docs Project** multi-agent system.
> Read this file in full before taking any action. It defines who does what,
> how the Writer and Reviewer agents hand off work, and the shared rules
> both must follow.

---

## 1. Project Overview

This is a documentation project authored and maintained by two cooperating agents:

- **Writer** — produces and revises documentation content.
- **Reviewer** — checks content for quality, accuracy, and style, then approves or requests changes.

The two agents do **not** edit at the same time. They take turns, coordinating
through the shared status file and the review queue described below. A document
is only considered **done** when the Reviewer has approved it.

### Repository layout

```
.
├── AGENTS.md            # This file — read first.
├── STATE.md             # Shared coordination ledger (single source of truth for status).
├── agents/
│   ├── writer.md        # Writer agent role card.
│   └── reviewer.md      # Reviewer agent role card.
├── docs/                # The documentation being produced (Writer owns content here).
├── review/
│   ├── queue.md         # Documents waiting for review / under review.
│   └── feedback/        # One feedback file per doc per review round (Reviewer writes here).
└── style-guide.md       # Shared writing & formatting rules (both agents obey).
```

---

## 2. The Agents

| Agent        | Role card            | Owns (may write)                                                              | Reads only                             |
| ------------ | -------------------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| **Writer**   | `agents/writer.md`   | `docs/**`, `review/queue.md` (status flips), `STATE.md` (its own rows)        | `review/feedback/**`, `style-guide.md` |
| **Reviewer** | `agents/reviewer.md` | `review/feedback/**`, `review/queue.md` (verdicts), `STATE.md` (its own rows) | `docs/**`, `style-guide.md`            |

**Golden rule:** an agent never edits a file the other agent owns. The Writer
writes docs; the Reviewer writes feedback. Both update only their own rows in
the shared ledger. This is what keeps the two from clobbering each other's work.

---

## 3. Coordination Protocol

All coordination flows through two shared, append-friendly artifacts:

1. **`STATE.md`** — the ledger. Every document has one row showing its current
   `status`, `owner` (whose turn it is), `round`, and a short note. This is the
   single source of truth. Before doing anything, an agent **reads `STATE.md`**
   to learn whose turn it is.
2. **`review/queue.md`** — the hand-off channel between Writer and Reviewer for
   documents that are in the review loop.

### Document lifecycle (state machine)

```
   ┌─────────┐   writer submits   ┌────────────┐   reviewer claims   ┌────────────┐
   │  DRAFT  │ ─────────────────▶ │  IN_REVIEW │ ──────────────────▶ │ REVIEWING  │
   └─────────┘                    └────────────┘                     └─────┬──────┘
        ▲                                                                   │
        │ changes requested (new round)                                     │ verdict
        │                                                                   ▼
   ┌─────────────────┐                                              ┌───────────────┐
   │ CHANGES_REQUESTED│ ◀───────────────────────────────────────── │   decision    │
   └─────────────────┘                                              └───────┬───────┘
                                                                            │ approved
                                                                            ▼
                                                                      ┌──────────┐
                                                                      │ APPROVED │  (done)
                                                                      └──────────┘
```

**Statuses:**

| Status              | Meaning                                                   | Owner (whose turn) |
| ------------------- | --------------------------------------------------------- | ------------------ |
| `DRAFT`             | Writer is actively authoring/editing.                     | Writer             |
| `IN_REVIEW`         | Writer has submitted; waiting for Reviewer to pick it up. | Reviewer           |
| `REVIEWING`         | Reviewer has claimed it and is reading.                   | Reviewer           |
| `CHANGES_REQUESTED` | Reviewer returned feedback; Writer must revise.           | Writer             |
| `APPROVED`          | Reviewer signed off. **Document is done.**                | — (locked)         |

Only the owner of a document may move it to its next state, and only along the
arrows above. No agent may skip states or take an action when it is not its turn.

### Turn-taking checklist (every agent, every cycle)

1. **Read `STATE.md`.** Find documents where `owner` == _you_.
2. If none are yours, **do nothing** and report "no work for me this cycle."
3. Pick the highest-priority document that is yours.
4. Do your work (see your role card for specifics).
5. Update **only your own row** in `STATE.md`: set the new `status`, flip `owner`
   to the other agent (or `—` if APPROVED), bump `round` if a new review round
   starts, and write a one-line note.
6. Update `review/queue.md` if the document entered or left the review loop.
7. Stop. Never act on a document whose `owner` is the other agent.

---

## 4. Hand-off Contracts

### Writer → Reviewer (submitting for review)

1. Writer finishes editing the doc in `docs/`.
2. Writer adds/updates an entry in `review/queue.md` with: doc path, round
   number, and a short summary of what changed since the last round.
3. Writer sets the doc's `STATE.md` status to `IN_REVIEW` and `owner` to `Reviewer`.
4. Writer **stops touching that doc** until it comes back.

### Reviewer → Writer (returning feedback)

1. Reviewer reads the doc (read-only) and the style guide.
2. Reviewer writes a feedback file at
   `review/feedback/<doc-name>-round-<N>.md` containing a verdict
   (`APPROVED` or `CHANGES_REQUESTED`) and a numbered, actionable list of issues.
3. **If `CHANGES_REQUESTED`:** set status to `CHANGES_REQUESTED`, `owner` to
   `Writer`, bump `round`, and note the feedback file path in the queue.
4. **If `APPROVED`:** set status to `APPROVED`, `owner` to `—`, and remove the
   doc from `review/queue.md`. The Reviewer never edits the doc itself to "fix"
   things — it only describes what the Writer should change.

### Feedback addressing rule

When the Writer receives `CHANGES_REQUESTED`, it must address **every numbered
item** in the round's feedback file — either by making the change or by adding a
one-line reply in the queue explaining why not. The Writer then resubmits
(`IN_REVIEW`) and the cycle repeats with an incremented `round`.

---

## 5. Conflict & Concurrency Rules

- **One owner at a time.** The `owner` field in `STATE.md` is a soft lock. If you
  are not the owner, you have no write rights to that document or its feedback.
- **Disjoint write surfaces.** Writer writes `docs/**`; Reviewer writes
  `review/feedback/**`. They never overlap, so concurrent edits to different
  documents are safe.
- **Last-writer-wins is forbidden.** Always read `STATE.md` immediately before
  writing it, and only modify your own row, to avoid overwriting the other
  agent's status update.
- **Stalled hand-off:** if a document has sat in `IN_REVIEW` for more than the
  agreed window (default: the next two cycles) the Reviewer should claim it and
  move it to `REVIEWING`, or note the blocker in the queue.
- **Disagreement:** if the Writer disagrees with a feedback item, it does not
  silently ignore it — it records a rebuttal line in the queue and leaves the
  item open. Unresolved disagreements escalate to the human maintainer (see §7).

---

## 6. Shared Standards (both agents)

- Follow `style-guide.md` for tone, headings, terminology, and formatting. The
  Reviewer enforces it; the Writer applies it proactively.
- Markdown for all docs. One H1 per document. Sentence-case headings.
- Keep changes scoped: edit only the document you currently own.
- Every state change must leave a one-line note so the history is auditable.
- Never delete another agent's feedback or notes.

---

## 7. Escalation

Escalate to the human maintainer (do not loop indefinitely) when:

- The same document bounces `CHANGES_REQUESTED` → `IN_REVIEW` **3+ times** on the
  same unresolved issue.
- Writer and Reviewer disagree on a feedback item that blocks approval.
- A document needs information neither agent has (missing source, unclear scope).

Record the escalation as a row note in `STATE.md` with status left at its current
value and a `BLOCKED:` prefix in the note.

---

## 8. Quick Reference

- **Whose turn is it?** → Read the `owner` column in `STATE.md`.
- **Where do I write?** → Writer: `docs/**`. Reviewer: `review/feedback/**`.
- **How do I hand off?** → Flip `status` + `owner` in `STATE.md`, update `review/queue.md`.
- **When is a doc done?** → Status is `APPROVED` and `owner` is `—`.
- **What if it's not my turn?** → Do nothing; report no work this cycle.
