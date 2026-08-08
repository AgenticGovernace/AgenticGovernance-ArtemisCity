# Handoff Ledger — Writer ⇄ Reviewer (ATP transport)

This file is the shared, file-based medium for ATP messages between Scribe (Writer) and
Ledger (Reviewer). Both agents **append** entries here; nobody edits past entries. Each
entry uses the ATP header defined in `AGENTS.md` → Communication.

Entry template (copy, fill, append at the bottom):

```
### <ISO timestamp> — <Action Type>
- Mode: Writer→Reviewer | Reviewer→Writer
- Context: <draft filename> (rev <n>)
- Priority: Routine | Elevated | Urgent
- Action Type: ReviewRequest | RevisionSubmitted | ReviewReturned | Approved | Blocked | ConflictRaised | Ack | Decline
- TargetZone: drafts/<file> | reviews/<file>
- Special Instructions: <e.g., addresses N1, N2; N3 disputed>
```

---

<!-- Example of a full round-trip (delete once real entries begin) -->

### 2026-06-16T00:00:00Z — ReviewRequest
- Mode: Writer→Reviewer
- Context: setup-guide.md (rev 1)
- Priority: Routine
- Action Type: ReviewRequest
- TargetZone: drafts/setup-guide.md
- Special Instructions: First draft, please review for accuracy and audience fit.

### 2026-06-16T00:05:00Z — Ack
- Mode: Reviewer→Writer
- Context: setup-guide.md (rev 1)
- Priority: Routine
- Action Type: Ack
- TargetZone: drafts/setup-guide.md
- Special Instructions: Received, reviewing now.

### 2026-06-16T00:20:00Z — ReviewReturned
- Mode: Reviewer→Writer
- Context: setup-guide.md (rev 1)
- Priority: Routine
- Action Type: ReviewReturned
- TargetZone: reviews/setup-guide.review.md
- Special Instructions: Verdict=revise. 1 major (N1), 2 minor (N2, N3). See review file.

<!-- Real entries below this line -->
