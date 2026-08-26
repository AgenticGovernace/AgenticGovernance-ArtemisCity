# drafts/ — Writer-owned

Document drafts live here. **Scribe (Writer) writes; Ledger (Reviewer) reads only.**

Each draft is a Markdown file with front-matter:

```
---
status: draft        # draft | revising
revision: 1
addresses: []        # review note IDs resolved in this revision, e.g. [N1, N3]
---
```

A draft is graduated out of this loop when the Reviewer records an `approve` verdict for it
in `handoff.md`.
