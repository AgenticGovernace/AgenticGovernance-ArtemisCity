#!/usr/bin/env python3
"""CompSuite — entry point.

Wires the audit pipeline together from ``config/compsuite.toml`` and runs the
watch loop. CompSuite watches ``voice_logs/`` and ``outputs/``, classifies every
file event as Normal / Warning / Error, escalates only above Warning (Error
only), writes daily audit logs, emits a reflection every ~50 actions, and
records action-level provenance for every read and write.

Usage::

    python compsuite.py run                 # run unattended (daemon)
    python compsuite.py run --cycles 5      # bounded run (testing)
    python compsuite.py scan                # one scan/diff/process cycle
    python compsuite.py selftest            # verify the policy invariants
    python compsuite.py config              # print the resolved configuration

The operating contract is AGENTS.md; this file is the executable seam.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compsuite.classifier import FileEvent, Severity, classify_event
from compsuite.escalation import Escalator, should_escalate
from compsuite.provenance import ProvenanceLedger
from compsuite.reflection import ReflectionEngine
from compsuite.watcher import WatchConfig, Watcher

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "compsuite.toml"


# --------------------------------------------------------------------------- #
# Config loading
# --------------------------------------------------------------------------- #


def _load_toml(path: Path) -> dict:
    """Parse the config file.

    Prefers the stdlib ``tomllib`` (3.11+), then optional ``tomli`` (3.10-),
    and finally falls back to a tiny built-in reader (``_minimal_toml``) so
    CompSuite stays dependency-free and runnable everywhere. The built-in
    reader supports exactly the subset this project's config uses: ``[tables]``,
    ``key = "string" | number | bool``, and single-line arrays.
    """
    try:
        import tomllib as toml_reader  # Python 3.11+

        with path.open("rb") as fh:
            return toml_reader.load(fh)
    except ModuleNotFoundError:
        pass
    try:
        import tomli as toml_reader  # type: ignore  # optional on 3.10-

        with path.open("rb") as fh:
            return toml_reader.load(fh)
    except ModuleNotFoundError:
        # Dependency-free last resort.
        return _minimal_toml(path.read_text(encoding="utf-8"))


def _minimal_toml(text: str) -> dict:
    """Parse the restricted TOML subset used by ``config/compsuite.toml``.

    This is deliberately small — it is NOT a general TOML parser. It exists only
    so the agent runs without ``tomllib``/``tomli``. It handles tables,
    scalar string/int/float/bool values, single-line arrays, and ``#`` comments.
    """
    import ast

    def parse_scalar(token: str):
        token = token.strip()
        if token.startswith("[") and token.endswith("]"):
            inner = token[1:-1].strip()
            if not inner:
                return []
            return [parse_scalar(part) for part in _split_top_level(inner)]
        low = token.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if (token.startswith('"') and token.endswith('"')) or (
            token.startswith("'") and token.endswith("'")
        ):
            return ast.literal_eval(token)
        try:
            return int(token)
        except ValueError:
            pass
        try:
            return float(token)
        except ValueError:
            return token  # leave as raw string

    result: dict = {}
    current = result
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            table = line[1:-1].strip()
            current = result.setdefault(table, {})
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            current[key.strip()] = parse_scalar(val)
    return result


def _strip_comment(line: str) -> str:
    """Remove a trailing ``#`` comment that is outside any quotes."""
    out, in_str, quote = [], False, ""
    for ch in line:
        if in_str:
            out.append(ch)
            if ch == quote:
                in_str = False
        elif ch in ("'", '"'):
            in_str = True
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _split_top_level(inner: str) -> list[str]:
    """Split a comma-separated array body, respecting quotes."""
    parts, buf, in_str, quote = [], [], False, ""
    for ch in inner:
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
        elif ch in ("'", '"'):
            in_str = True
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts


def _resolve_root(p: str) -> Path:
    """Resolve a configured path against the project root unless absolute."""
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"error: config not found at {CONFIG_PATH}")
    return _load_toml(CONFIG_PATH)


def build_watcher(cfg: dict) -> Watcher:
    """Construct a fully wired :class:`Watcher` from a parsed config dict."""
    cs = cfg.get("compsuite", {})
    cl = cfg.get("classification", {})
    es = cfg.get("escalation", {})
    rf = cfg.get("reflection", {})
    lg = cfg.get("logging", {})

    log_dir = _resolve_root(lg.get("log_dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    # Resume the run id from the last checkpoint so restarts are continuous.
    prior = ProvenanceLedger.load_checkpoint(log_dir)
    ledger_kwargs = {"flush_each_record": bool(lg.get("flush_each_record", True))}
    ledger = ProvenanceLedger(log_dir=log_dir, **ledger_kwargs)
    if prior and prior.get("parent_run_id"):
        ledger.parent_run_id = prior["parent_run_id"]

    watch_roots = [
        _resolve_root(r) for r in cs.get("watch_roots", ["voice_logs", "outputs"])
    ]
    for r in watch_roots:
        r.mkdir(parents=True, exist_ok=True)  # ensure the trees exist to watch

    watch_cfg = WatchConfig(
        watch_roots=watch_roots,
        poll_interval_seconds=float(cs.get("poll_interval_seconds", 2.0)),
        backend=str(cs.get("backend", "poll")),
        voice_logs_allowed_ext=list(cl.get("voice_logs_allowed_ext", [])),
        outputs_allowed_ext=list(cl.get("outputs_allowed_ext", [])),
        forbidden_ext=list(cl.get("forbidden_ext", [])),
        warn_on_unknown_extension=bool(cl.get("warn_on_unknown_extension", True)),
        warn_on_zero_byte=bool(cl.get("warn_on_zero_byte", True)),
        warn_on_delete=bool(cl.get("warn_on_delete", True)),
        error_on_out_of_tree=bool(cl.get("error_on_out_of_tree", True)),
        error_on_classifier_failure=bool(cl.get("error_on_classifier_failure", True)),
    )

    escalator = Escalator.from_config(
        ledger,
        log_dir,
        threshold_label=str(es.get("threshold", "Warning")),
        sinks=list(es.get("sinks", ["log"])),
        command=str(es.get("command", "")),
    )

    reflection = ReflectionEngine(
        ledger=ledger,
        log_dir=log_dir,
        every_n_actions=int(rf.get("every_n_actions", 50)),
    )

    return Watcher(
        config=watch_cfg,
        ledger=ledger,
        escalator=escalator,
        reflection=reflection,
        log_dir=log_dir,
    )


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #


def cmd_run(args: argparse.Namespace) -> int:
    watcher = build_watcher(load_config())
    sys.stderr.write(
        f"[CompSuite] run {watcher.ledger.parent_run_id} watching "
        f"{', '.join(str(r) for r in watcher.config.watch_roots)} "
        f"(poll {watcher.config.poll_interval_seconds}s); Ctrl-C to stop.\n"
    )
    watcher.run_forever(max_cycles=args.cycles)
    return 0


def cmd_scan(_args: argparse.Namespace) -> int:
    watcher = build_watcher(load_config())
    # Baseline then one diff cycle so a manual scan reports changes since last.
    watcher._snapshot = watcher._scan()  # noqa: SLF001 - intentional baseline
    results = watcher.run_once()
    for r in results:
        sys.stdout.write(f"{r.severity.label}\t{r.reason}\n")
    watcher.stop()
    sys.stderr.write(f"[CompSuite] {len(results)} event(s) processed.\n")
    return 0


def cmd_config(_args: argparse.Namespace) -> int:
    cfg = load_config()
    import json

    sys.stdout.write(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    """Verify the load-bearing invariants without touching the real trees.

    1. Severity ordering Normal < Warning < Error.
    2. The escalation gate escalates Error only.
    3. classify_event assigns the documented severities for representative
       events.
    """
    failures: list[str] = []

    # 1. ordering
    if not (Severity.NORMAL < Severity.WARNING < Severity.ERROR):
        failures.append("severity ordering is wrong")

    # 2. escalation gate — the core rule
    if should_escalate(Severity.NORMAL):
        failures.append("Normal escalated (must not)")
    if should_escalate(Severity.WARNING):
        failures.append("Warning escalated (must not)")
    if not should_escalate(Severity.ERROR):
        failures.append("Error did NOT escalate (must)")

    # 3. classification spot-checks
    rules = dict(
        voice_logs_allowed_ext=[".wav", ".json"],
        outputs_allowed_ext=[".json", ".md"],
        forbidden_ext=[".exe", ".sh"],
    )
    vroot = ROOT / "voice_logs"
    oroot = ROOT / "outputs"
    cases = [
        (FileEvent(vroot / "a.wav", "created", vroot, 100), Severity.NORMAL),
        (FileEvent(oroot / "r.md", "modified", oroot, 100), Severity.NORMAL),
        (FileEvent(oroot / "weird.zip", "created", oroot, 100), Severity.WARNING),
        (FileEvent(oroot / "empty.json", "created", oroot, 0), Severity.WARNING),
        (FileEvent(oroot / "x.json", "deleted", oroot, None), Severity.WARNING),
        (FileEvent(oroot / "mal.exe", "created", oroot, 10), Severity.ERROR),
        (FileEvent(Path("/tmp/escape.json"), "created", oroot, 10), Severity.ERROR),
    ]
    for ev, expected in cases:
        got = classify_event(ev, watch_roots=[vroot, oroot], **rules).severity
        if got != expected:
            failures.append(
                f"classify {ev.path.name} ({ev.kind}): expected {expected.label}, got {got.label}"
            )

    if failures:
        sys.stderr.write("SELFTEST FAILED:\n  - " + "\n  - ".join(failures) + "\n")
        return 1
    sys.stdout.write(
        "SELFTEST PASSED: severity ordering, escalation gate (Error-only), "
        "and classification rules all hold.\n"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compsuite",
        description=(
            "CompSuite: unattended file-audit agent. Watches voice_logs/ and "
            "outputs/, classifies events (Normal/Warning/Error), escalates only "
            "above Warning, writes daily logs + provenance, reflects every ~50 "
            "actions."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run unattended (daemon).")
    p_run.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="Stop after N poll cycles (for bounded/test runs). Omit for a daemon.",
    )
    p_run.set_defaults(func=cmd_run)

    p_scan = sub.add_parser("scan", help="Run a single scan/diff/process cycle.")
    p_scan.set_defaults(func=cmd_scan)

    p_cfg = sub.add_parser("config", help="Print the resolved configuration as JSON.")
    p_cfg.set_defaults(func=cmd_config)

    p_self = sub.add_parser("selftest", help="Verify policy invariants and exit.")
    p_self.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
