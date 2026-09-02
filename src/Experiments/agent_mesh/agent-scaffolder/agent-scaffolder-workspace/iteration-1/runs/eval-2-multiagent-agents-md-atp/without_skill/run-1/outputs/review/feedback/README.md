# Feedback files

The **Reviewer** writes one file per document per review round here, named:

```
<doc-name>-round-<N>.md
```

For example: `getting-started-round-1.md`.

Each file starts with a verdict line and, when changes are requested, a numbered
actionable list:

```markdown
# Feedback: docs/getting-started.md — round 1

Verdict: CHANGES_REQUESTED

1. The install command in the "Quick start" section is missing the `--save` flag. (style-guide §Commands)
2. Heading "Getting Started" should be sentence case: "Getting started". (style-guide §Headings)
3. The second paragraph repeats the first — cut one.
```

Rules:

- Only the **Reviewer** writes in this folder.
- The **Writer** reads these files but never edits them.
- Never delete past-round feedback — it is the audit trail.
