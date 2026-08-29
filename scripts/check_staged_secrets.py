#!/usr/bin/env python3
"""Block hardcoded secret VALUES in staged changes, not secret-shaped words.

This replaces a bare ``grep -lE "API_KEY|SECRET|PASSWORD"`` over staged file
names, which had three defects:

* it piped names through unquoted ``xargs``, so paths with spaces
  (``app/Artemis Agentic Memory Layer/...``, ``AGENTS 2.md``) split into
  nonexistent fragments and produced ``grep: ...: No such file`` noise;
* it grepped the WORKING TREE content of those files, so it judged text that
  was not part of the commit at all;
* it matched keywords rather than values, so documentation that merely names
  ``MCP_API_KEY`` failed the gate while an actual hardcoded credential like
  ``password = "hunter2-prod"`` was indistinguishable from it.  # pragma: allowlist secret

This scanner reads ``git diff --cached`` directly (added lines only — content
actually entering the commit), and flags only a *keyword assigned a concrete
value*. Placeholders, env-var indirection, and template syntax are recognised
and skipped, and a line carrying ``pragma: allowlist secret`` is always
accepted — the same escape hatch detect-secrets honours.

Matched values are printed masked. This tool must never echo a real secret.

Exit status: 0 when clean, 1 when a probable hardcoded secret is staged.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed argv, no shell, repo tooling
import sys
from typing import Iterator, NamedTuple

#: Files whose content legitimately contains high-entropy or secret-shaped
#: strings that are not credentials (lockfile hashes, scanner baselines,
#: documented example env files).
SKIP_FILE = re.compile(
    r"(^|/)(\.secrets\.baseline|package-lock\.json|yarn\.lock|uv\.lock"
    r"|[^/]*\.env\.example|[^/]*\.env\.template|env\.example)$"
    # Vendored third-party code and captured runtime logs: not project source.
    # detect-secrets still scans them; this hook guards hand-written changes.
    r"|(^|/)node_modules/|(^|/)site-packages/|(^|/)dist-packages/"
    r"|(^|/)lib/python[0-9.]+/|(^|/)logs/"
)

_KEYWORD = (
    r"(?:api[_-]?key|apikey|secret|passwd|password|token"
    r"|private[_-]?key|access[_-]?key|auth[_-]?key)"
)

#: ``SOME_API_KEY = "actualvalue"`` — a secret-ish name assigned a concrete  # pragma: allowlist secret
#: value of plausible credential length. The quote must close if it opened.
ASSIGNMENT = re.compile(
    rf"(?i)\b(?P<key>[A-Z0-9_\-]*{_KEYWORD}[A-Z0-9_\-]*)"
    rf"\s*[:=]\s*(?P<quote>[\"'`]?)(?P<value>[A-Za-z0-9+/=_\-.]{{8,}})(?P=quote)"
)

#: Values or lines that are self-evidently not credentials.
PLACEHOLDER = re.compile(
    r"(?i)(your[_-]|example|placeholder|change[_-]?me|dummy|sample"
    r"|not[-_]?a[-_]?real|redacted|to[-_]?be[-_]?set|fill[-_]?in"
    r"|my[-_]secret|\.\.\.|x{4,}|\*{3,})"
)

#: The value is fetched at runtime or templated — not a literal credential.
INDIRECTION = re.compile(
    r"(?i)(os\.environ|os\.getenv|getenv\(|process\.env|import\.meta\.env"
    r"|\$\{|\$\(|\{\{|%\(|secrets\.|vault\.|keyring\.)"
)

#: Explicit reviewer sign-off that a match is a known placeholder.
ALLOWLISTED = re.compile(r"(?i)(pragma:\s*allowlist\s+secret|#\s*nosec\b)")


class Finding(NamedTuple):
    """One probable hardcoded secret in the staged diff."""

    path: str
    line: int
    key: str
    masked_value: str


def added_lines(diff_text: str) -> Iterator[tuple[str, int, str]]:
    """Yield ``(path, new_line_number, text)`` for every added line in a diff.

    Paths are taken from the ``+++ b/...`` header verbatim, so names containing
    spaces survive intact — the defect that made the previous grep pipeline
    split them apart.
    """
    path: str | None = None
    line_no = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].rstrip("\t")
            if target == "/dev/null":
                path = None
            else:
                path = target[2:] if target.startswith("b/") else target
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            line_no = int(match.group(1)) if match else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            if path is not None:
                yield path, line_no, raw[1:]
            line_no += 1
        elif not raw.startswith("-") and not raw.startswith("\\"):
            line_no += 1


def mask(value: str) -> str:
    """Render a matched value without disclosing it."""
    visible = value[:2]
    return f"{visible}{'*' * max(len(value) - 2, 4)}"


def scan_line(path: str, line_no: int, text: str) -> Finding | None:
    """Return a Finding when a staged line assigns a concrete secret value."""
    if SKIP_FILE.search(path):
        return None
    if ALLOWLISTED.search(text) or INDIRECTION.search(text):
        return None
    match = ASSIGNMENT.search(text)
    if match is None:
        return None
    if PLACEHOLDER.search(text):
        return None
    value = match.group("value")
    if len(set(value)) <= 2:  # e.g. "aaaaaaaa", "········"
        return None
    if not match.group("quote"):
        # An unquoted value in source code is usually an expression, not a
        # literal: `token = get_token(...)`, `password = Prompt.ask(...)`,
        # `apiKey = req.headers`. Skip pure identifier/attribute chains and
        # call expressions. Dotenv-style secrets (`KEY=a1b2c3...`) survive
        # this: they contain digits or separators that identifiers lack.
        rest = text[match.end() :].lstrip()
        looks_like_identifier = re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.]*", value
        ) and not any(ch.isdigit() for ch in value)
        if looks_like_identifier or rest.startswith("("):
            return None
    return Finding(path, line_no, match.group("key"), mask(value))


def scan_diff(diff_text: str) -> list[Finding]:
    """Scan a unified diff and return every probable hardcoded secret."""
    findings = []
    for path, line_no, text in added_lines(diff_text):
        finding = scan_line(path, line_no, text)
        if finding is not None:
            findings.append(finding)
    return findings


def staged_diff() -> str:
    """Return the staged diff for added/copied/modified files."""
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [
            "git",
            "diff",
            "--cached",
            "--no-color",
            "--unified=0",
            "--diff-filter=ACM",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> int:
    """Entry point for the pre-commit hook."""
    findings = scan_diff(staged_diff())
    if not findings:
        return 0
    print("Probable hardcoded secrets in staged changes:")
    for finding in findings:
        print(
            f"  {finding.path}:{finding.line}: "
            f"{finding.key} = {finding.masked_value}"
        )
    print(
        "Move real credentials to the environment (.env stays untracked), or\n"
        "append `# pragma: allowlist secret` to a line that is a genuine\n"
        "placeholder. Values above are masked; nothing was disclosed."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
