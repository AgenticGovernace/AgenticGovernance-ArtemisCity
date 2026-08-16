#!/usr/bin/env python3
"""RefactorBot — a CLI refactoring agent.

RefactorBot proposes performance-oriented refactors and emits them as raw
unified diffs. Its behavior is bound by three rules, which are enforced both by
the system prompt sent to the model (see ``prompts/system_prompt.md``) and by
the output handling in this module:

    1. Output raw diffs only.
    2. Maintain a formal, technical tone at all times.
    3. Annotate the expected performance gain for every changed line.

This entry point is intentionally model-agnostic. The ``build_request``
function assembles the system prompt and the file payload; wire it to whichever
LLM backend you use. ``emit_diff`` guarantees the output stays a raw diff.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Resolve project-relative paths so the tool works regardless of cwd.
ROOT = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = ROOT / "prompts" / "system_prompt.md"
CONFIG_PATH = ROOT / "config" / "refactorbot.toml"

# Marker token that every performance annotation must contain. Used to verify
# Rule 3 compliance before any diff is emitted.
PERF_MARKER = "PERF:"


def load_system_prompt() -> str:
    """Return the persona contract that constrains the model's behavior."""
    if not SYSTEM_PROMPT_PATH.exists():
        sys.exit(
            f"error: system prompt not found at {SYSTEM_PROMPT_PATH}. "
            "The persona contract is required for operation."
        )
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def load_config() -> dict:
    """Load runtime configuration from the TOML file.

    Falls back to documented defaults when the file or the ``tomllib``/``tomli``
    parser is unavailable, so the tool degrades gracefully.
    """
    defaults = {
        "model": "claude-3-5-sonnet",
        "diff_context_lines": 3,
        "min_speedup": 1.10,
        "require_perf_annotations": True,
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        try:
            import tomllib as toml_reader  # Python 3.11+
        except ModuleNotFoundError:  # pragma: no cover - older interpreters
            import tomli as toml_reader  # type: ignore
        with CONFIG_PATH.open("rb") as fh:
            data = toml_reader.load(fh)
        merged = dict(defaults)
        merged.update(data.get("refactorbot", {}))
        return merged
    except Exception:
        # Configuration must never crash the tool; defaults are safe.
        return defaults


def read_targets(paths: list[str]) -> list[tuple[str, str]]:
    """Read each target file, returning (path, source) pairs."""
    targets: list[tuple[str, str]] = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            sys.exit(f"error: '{p}' is not a readable file.")
        targets.append((str(path), path.read_text(encoding="utf-8")))
    return targets


def build_request(
    system_prompt: str, targets: list[tuple[str, str]], config: dict
) -> dict:
    """Assemble the model request payload.

    Returns a backend-neutral dict. Adapt this to your LLM client of choice
    (e.g., the Anthropic Messages API). The contract is: send ``system`` as the
    system prompt and the rendered ``user`` content as the user turn.
    """
    rendered_files = []
    for path, source in targets:
        rendered_files.append(f"### FILE: {path}\n```\n{source}\n```")
    user_content = (
        "Refactor the following file(s) for performance. Emit a single unified "
        "diff covering all proposed changes. Comply with all three rules in the "
        "system prompt without exception.\n\n"
        f"min_speedup threshold = {config['min_speedup']}\n"
        f"diff_context_lines = {config['diff_context_lines']}\n\n"
        + "\n\n".join(rendered_files)
    )
    return {
        "model": config["model"],
        "system": system_prompt,
        "user": user_content,
    }


def call_model(request: dict) -> str:  # pragma: no cover - integration point
    """Send the request to the configured LLM backend and return raw text.

    This is the single integration seam. It is left unimplemented so the
    scaffold runs without credentials. Replace the body with a call to your
    provider. The function must return the model's raw text response (expected
    to already be a unified diff per the system prompt).

    Example (Anthropic):

        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=request["model"],
            max_tokens=4096,
            system=request["system"],
            messages=[{"role": "user", "content": request["user"]}],
        )
        return msg.content[0].text
    """
    raise NotImplementedError(
        "call_model is the LLM integration seam. Implement it against your "
        "provider. See the docstring for an Anthropic example, or set "
        "REFACTORBOT_DRY_RUN=1 to inspect the assembled request without a call."
    )


def emit_diff(diff_text: str, output: str | None, config: dict) -> int:
    """Write the diff to stdout or a file after enforcing the output contract.

    Rule 1: the payload is emitted verbatim as a raw diff, with no wrapping.
    Rule 3: if annotations are required, refuse to emit a non-empty diff that
    lacks at least one ``PERF:`` annotation.
    """
    stripped = diff_text.strip()

    # An empty diff is valid output: it means no beneficial refactor exists.
    if not stripped:
        return 0

    if config.get("require_perf_annotations", True) and PERF_MARKER not in stripped:
        sys.exit(
            "error: model output contained changes without required "
            f"'{PERF_MARKER}' annotations (Rule 3 violation); refusing to emit."
        )

    payload = stripped + "\n"
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


def cmd_refactor(args: argparse.Namespace) -> int:
    """Handle the ``refactor`` subcommand."""
    config = load_config()
    system_prompt = load_system_prompt()
    targets = read_targets(args.files)
    request = build_request(system_prompt, targets, config)

    # Dry-run mode lets users verify the assembled request without a backend.
    if os.environ.get("REFACTORBOT_DRY_RUN") == "1":
        sys.stderr.write(
            "[dry-run] model={model}\n[dry-run] system prompt: {n} chars\n"
            "[dry-run] user payload follows on stdout\n".format(
                model=request["model"], n=len(request["system"])
            )
        )
        sys.stdout.write(request["user"] + "\n")
        return 0

    diff_text = call_model(request)
    return emit_diff(diff_text, args.output, config)


def cmd_persona(_args: argparse.Namespace) -> int:
    """Print the active persona contract (system prompt)."""
    sys.stdout.write(load_system_prompt())
    if not load_system_prompt().endswith("\n"):
        sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refactorbot",
        description=(
            "RefactorBot: emits raw unified diffs proposing performance "
            "refactors, in a formal register, with a per-line performance "
            "rationale."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_refactor = sub.add_parser(
        "refactor", help="Analyze file(s) and emit a raw unified diff."
    )
    p_refactor.add_argument(
        "files", nargs="+", help="One or more source files to refactor."
    )
    p_refactor.add_argument(
        "-o",
        "--output",
        default=None,
        help="Write the diff to this path instead of stdout.",
    )
    p_refactor.set_defaults(func=cmd_refactor)

    p_persona = sub.add_parser(
        "persona", help="Print the persona contract (system prompt)."
    )
    p_persona.set_defaults(func=cmd_persona)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
