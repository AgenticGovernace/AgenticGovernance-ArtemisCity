# RefactorBot — Reference Session

This transcript demonstrates the exact output contract. It is the canonical
example of what a compliant RefactorBot response looks like: a raw unified
diff, formal register, and a `PERF:` annotation for every changed hunk.

## Input file: `aggregate.py`

```python
def count_words(documents):
    counts = {}
    for doc in documents:
        for word in doc.split():
            if word in counts.keys():
                counts[word] = counts[word] + 1
            else:
                counts[word] = 1
    return counts


def first_match(items, predicate):
    matches = [x for x in items if predicate(x)]
    if len(matches) > 0:
        return matches[0]
    return None
```

## Invocation

```bash
./refactorbot.py refactor aggregate.py
```

## Output (raw diff, emitted verbatim to stdout)

```
--- a/aggregate.py
+++ b/aggregate.py
@@ -1,11 +1,9 @@ def count_words(documents):
-    counts = {}
+    # PERF: dict.keys() built a fresh view and the `in` test scanned it,
+    # PERF: yielding O(k) membership per word (O(n*k) overall); Counter
+    # PERF: uses amortized O(1) hashing in a single C-level pass.
+    from collections import Counter
+    counts = Counter()
     for doc in documents:
-        for word in doc.split():
-            if word in counts.keys():
-                counts[word] = counts[word] + 1
-            else:
-                counts[word] = 1
+        counts.update(doc.split())
     return counts
@@ -14,7 +12,7 @@ def first_match(items, predicate):
-    matches = [x for x in items if predicate(x)]
-    if len(matches) > 0:
-        return matches[0]
-    return None
+    # PERF: prior code materialized the full filtered list (O(n) time and
+    # PERF: O(n) memory) only to read element 0; next() with a generator
+    # PERF: short-circuits on the first hit (best case O(1), no allocation).
+    return next((x for x in items if predicate(x)), None)
```

## Notes on compliance

- **Rule 1 (raw diffs only):** the output is a single unified diff with no
  surrounding prose, no "here is the change" preamble, and no trailing summary.
- **Rule 2 (formal tone):** annotations use precise terminology
  ("amortized O(1) hashing", "materialized the full filtered list") with no
  casual phrasing.
- **Rule 3 (per-line rationale):** each hunk carries `PERF:` lines stating both
  the mechanism and the expected gain, including the asymptotic change
  (`O(n*k)` accumulation eliminated; `O(n)` allocation removed via
  short-circuiting).

## Empty-diff case

When no refactor clears the `min_speedup` threshold, RefactorBot emits no
hunks and exits `0`:

```bash
$ ./refactorbot.py refactor already_optimal.py
$ echo $?
0
```
