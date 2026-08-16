# Handoff log (append-only)

One line per handoff between the Writer and Reviewer. Never edit or delete prior lines — append
only. This is the lightweight file-based audit trail referenced in `AGENTS.md`.

Format:
```
<ISO-8601 timestamp> | <from> → <to> | <doc-slug> r<round> | <action-type> | <status/verdict> | <notes: feedback IDs or open count>
```

Example:
```
2026-06-16T14:00Z | writer → reviewer | getting-started r1 | draft-ready-for-review | in-review | initial draft
2026-06-16T14:05Z | reviewer → writer | getting-started r1 | feedback-returned | changes-requested | 3 open (R1-01..03)
2026-06-16T15:10Z | writer → reviewer | getting-started r2 | revision-ready | in-review | addressed R1-01,R1-02,R1-03
```

<!-- Append real handoff lines below this line. -->
