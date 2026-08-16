# RefactorBot

A command-line refactoring assistant. RefactorBot analyzes source files and
proposes performance-oriented refactors. It operates under three strict,
non-negotiable rules:

1. **Raw diffs only.** Every proposed change is emitted as a unified diff
   (`diff -u` / `git diff` format). RefactorBot never prints prose-wrapped
   code blocks, summaries of changes, or "here is what I changed" narration.
   The diff is the deliverable.
2. **Formal tone at all times.** RefactorBot communicates in precise,
   professional, technical language. No casual phrasing, slang, emoji,
   exclamatory enthusiasm, or conversational filler.
3. **Per-line performance rationale.** Each changed line (or contiguous hunk)
   is annotated with the expected performance gain and the mechanism behind
   it, delivered as diff-comment lines so the annotations travel with the diff.

## Why these rules exist

RefactorBot is built to be embedded in automated pipelines (CI, pre-commit
hooks, review bots). Tools downstream consume its output, so the output must be
machine-parseable (valid unified diff) and free of editorializing. The formal
tone and quantified per-line rationale make the bot's reasoning auditable in a
code-review context.

## Installation

```bash
# Python 3.9+ required
python -m pip install -r requirements.txt

# Make the CLI executable
chmod +x refactorbot.py
```

## Usage

```bash
# Analyze a single file and emit a raw unified diff to stdout
./refactorbot.py refactor path/to/module.py

# Analyze multiple files
./refactorbot.py refactor src/a.py src/b.py

# Write the diff to a file instead of stdout
./refactorbot.py refactor src/a.py --output changes.diff

# Print the active system prompt / persona contract
./refactorbot.py persona
```

The `refactor` command always prints a unified diff. The annotations describing
the performance gain for each line are emitted as `#` diff-comment lines
adjacent to the relevant hunk, so the entire payload remains a valid patch that
can be piped to `git apply` (the comment lines are ignored on apply).

## Output contract

Every invocation that produces changes yields output of this shape:

```diff
--- a/example.py
+++ b/example.py
@@ -3,5 +3,5 @@ def aggregate(records):
-    total = 0
-    for r in records:
-        total = total + r.value
+    # PERF: replaces O(n) Python-level accumulation with a single C-level
+    # PERF: reduction; expected ~4-8x throughput on large iterables.
+    total = sum(r.value for r in records)
```

If RefactorBot determines that no beneficial refactor exists, it emits an empty
diff and exits with status code `0`.

## Project layout

```
.
├── README.md              This file.
├── refactorbot.py         CLI entry point.
├── prompts/
│   └── system_prompt.md   The persona contract enforcing the three rules.
├── config/
│   └── refactorbot.toml   Runtime configuration and tunable thresholds.
├── examples/
│   └── sample_session.md  A reference input/output transcript.
├── requirements.txt       Python dependencies.
└── .gitignore
```

## Configuration

See `config/refactorbot.toml` for tunable behavior (diff context lines, the
minimum estimated speedup required before a change is proposed, and the LLM
model identifier). The persona contract in `prompts/system_prompt.md` is the
authoritative definition of the bot's behavior and tone.

## License

Released under the MIT License. See repository root for terms.
