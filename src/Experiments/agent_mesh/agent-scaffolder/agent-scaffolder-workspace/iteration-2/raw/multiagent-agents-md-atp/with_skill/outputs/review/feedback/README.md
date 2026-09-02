# Review feedback format

The Reviewer (Critic) writes one file per review round here, named `<doc-slug>.r<round>.md`
(e.g., `getting-started.r1.md`). The Writer (Scribe) reads it as the to-do list for the next
revision and resolves items **by ID**. Never delete a feedback file — it is the audit trail
for the review loop.

## Rules

- Every item has a **stable ID** (`R<round>-<nn>`, e.g., `R1-03`). Reuse the same ID across
  rounds for the same issue so it can be tracked to resolution.
- Every item has a **severity**: `Blocking` (must fix before approval), `Should-fix`
  (strongly recommended), or `Nit` (optional polish).
- Every item has a **location** (section/heading/line) and a **concrete suggested change**.
- Carry forward: a new round's file must restate any still-open IDs from the prior round.
- End the file with exactly one verdict line:
  `VERDICT: changes-requested` or `VERDICT: approved`.

## Template

```markdown
# Feedback — <doc-slug> — round <n>

Reviewer: Critic | Date: <ISO-8601> | Draft reviewed: docs/<doc-slug>.md

## Open items

- **R<n>-01** [Blocking] (Location: <section/line>) <issue>. Suggested change: <fix>.
- **R<n>-02** [Should-fix] (Location: <section/line>) <issue>. Suggested change: <fix>.
- **R<n>-03** [Nit] (Location: <section/line>) <issue>. Suggested change: <fix>.

## Carried forward (still open from prior rounds)

- **R<n-1>-04** [Blocking] (Location: <…>) <status note>.

VERDICT: changes-requested
```
