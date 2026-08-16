# reviews/ — Reviewer-owned

Structured reviews live here. **Ledger (Reviewer) writes; Scribe (Writer) reads only.**

One review file per draft, mirroring the draft name:
`drafts/setup-guide.md` → `reviews/setup-guide.review.md`.

Review file shape:

```
# Review — <draft filename> (rev <n>)
**Verdict:** approve | revise | block

## Notes
- **N1** [blocker|major|minor|nit] — <location>: <issue + suggested direction>
- **N2** [ ... ] — ...
```

Severity sets the verdict: any open `blocker` → `block`; any `major` → `revise`; only
`minor`/`nit` remaining → `approve`.
