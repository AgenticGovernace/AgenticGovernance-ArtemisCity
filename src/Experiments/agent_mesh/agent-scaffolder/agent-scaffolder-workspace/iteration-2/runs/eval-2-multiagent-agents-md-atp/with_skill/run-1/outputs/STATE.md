# STATE.md — coordination single source of truth

> Both agents read this on entry and update it on every handoff. A doc has exactly **one**
> owner at a time. Acquire ownership (set `owner`) before working; release it (hand to the
> other agent) in the same edit as your handoff. If a doc lists the other agent as owner,
> do not touch its files.

## Status legend

- `drafting` — Writer is authoring/revising; owner = `writer`.
- `in-review` — Reviewer is reviewing; owner = `reviewer`.
- `changes-requested` — Reviewer returned feedback; owner = `writer`.
- `approved` — Reviewer approved; loop complete; owner = `none`.
- `blocked` — escalated to human; owner = `human`.

## Docs in flight

| Doc slug        | Owner | Status      | Round | Last handoff (UTC) | Notes                                        |
| --------------- | ----- | ----------- | ----- | ------------------ | -------------------------------------------- |
| _example-intro_ | none  | not-started | 0     | —                  | template row; replace when a real doc starts |

<!--
Example of a live row mid-loop:
| getting-started | reviewer | in-review | 2 | 2026-06-16T14:05Z | round 2; 3 items open from r1 |
-->
