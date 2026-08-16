# Style Guide

> Shared writing and formatting rules. The **Writer** applies these proactively;
> the **Reviewer** enforces them. Read-only for both agents — changes to this
> guide go through the human maintainer.

## Voice & tone

- Write for a competent reader who is new to *this* project, not new to software.
- Be direct and active. "Run the command," not "the command should be run."
- Prefer short sentences. Cut filler ("simply," "just," "of course").

## Structure

- Exactly **one H1** per document — the title.
- Headings in **sentence case** ("Getting started", not "Getting Started").
- Lead with the most useful information; put background later.
- No empty sections and no `TODO` left in an approved document.

## Formatting (Markdown)

- Fenced code blocks with a language tag (` ```bash `, ` ```json `).
- Inline code for commands, flags, filenames, and identifiers: `--save`, `docs/`.
- Use ordered lists for steps, unordered lists for sets of options.
- One blank line between block elements; no trailing whitespace.

## Terminology

- Refer to the two agents as **Writer** and **Reviewer** (capitalized).
- Refer to the status ledger as `STATE.md` and the hand-off file as the **review queue**.
- Be consistent: pick one term for a concept and use it throughout a document.

## Commands & examples

- Show the exact command, including required flags.
- Show expected output when it helps the reader confirm success.
- Never include real secrets, tokens, or credentials in examples.

## Review-relevant checklist (what the Reviewer checks against)

1. One H1, sentence-case headings.
2. Code blocks tagged; commands complete.
3. Active voice, no filler.
4. Consistent terminology.
5. No TODOs, no broken links, no leftover placeholder text.
