"""Package entry point for Artemis City.

Enables running the project as a module:

    python -m src                          # Interactive Artemis CLI (default)
    python -m src --orchestrator           # MCP orchestrator pipeline
    python -m src --atp                    # Reserved ATP entrypoint
    python -m src "status"                 # One-shot Artemis command
    python -m src --plan plan.json         # Execute a plan file
"""

import argparse
import sys

ATP_ADAPTER_PENDING_MESSAGE = (
    "--atp is reserved for the forthcoming Routing Kernel ATP adapter; "
    "use the default CLI or --orchestrator for now.\n"
)


def entry() -> None:
    """Dispatch ``python -m src`` arguments to the selected Artemis CLI."""
    parser = argparse.ArgumentParser(
        description="Artemis City — Agentic Governance Platform",
        add_help=False,
    )
    parser.add_argument(
        "--orchestrator",
        action="store_true",
        help="Run the MCP orchestrator pipeline.",
    )
    parser.add_argument(
        "--atp",
        action="store_true",
        help="Reserved for the forthcoming Routing Kernel ATP adapter.",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show this help message and exit.",
    )
    args, remaining = parser.parse_known_args()

    forwarded_args = list(remaining)
    if args.help and not args.orchestrator and not args.atp and not remaining:
        parser.print_help()
        sys.exit(0)
    if args.help:
        forwarded_args.append("--help")
    if args.atp:
        sys.stderr.write(ATP_ADAPTER_PENDING_MESSAGE)
        raise SystemExit(2)

    sys.argv = [sys.argv[0], *forwarded_args]

    if args.orchestrator:
        from src.launch.main import main
    else:
        from src.interface.artemis_cli import main

    main()


if __name__ == "__main__":
    entry()
