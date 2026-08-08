# STATE.md — Shared Coordination Ledger

> **Single source of truth for whose turn it is.** Before acting, read this file.
> Each document has exactly one row. Update **only your own row**, and always
> re-read this file immediately before writing it.
>
> - `status`: one of `DRAFT`, `IN_REVIEW`, `REVIEWING`, `CHANGES_REQUESTED`, `APPROVED`.
> - `owner`: whose turn it is (`Writer`, `Reviewer`, or `—` when `APPROVED`).
> - `round`: review round counter, starts at 0, +1 each time changes are requested.
> - `updated_by`: which agent last wrote this row.
> - `note`: one line. Prefix with `BLOCKED:` if escalated (see AGENTS.md §7).

## Documents

| Document | Status | Owner | Round | Updated by | Note |
|----------|--------|-------|-------|------------|------|
| docs/getting-started.md | DRAFT | Writer | 0 | Writer | Seed row — authoring not yet started. |
| docs/configuration.md | DRAFT | Writer | 0 | Writer | Seed row — authoring not yet started. |

<!--
HOW TO USE THIS TABLE

Writer submits getting-started.md for review:
| docs/getting-started.md | IN_REVIEW | Reviewer | 0 | Writer | Submitted round 0; see review/queue.md. |

Reviewer claims it:
| docs/getting-started.md | REVIEWING | Reviewer | 0 | Reviewer | Reviewing round 0. |

Reviewer requests changes:
| docs/getting-started.md | CHANGES_REQUESTED | Writer | 1 | Reviewer | 3 issues in review/feedback/getting-started-round-1.md. |

Reviewer approves:
| docs/getting-started.md | APPROVED | — | 2 | Reviewer | Signed off round 2. Done. |

Add a new row to register a new document. Never delete rows — history is auditable.
-->
