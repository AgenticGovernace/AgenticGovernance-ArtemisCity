"""Package entry point for Artemis City.

Enables running the project via: python -m src

Dispatches to the ATP-enabled interactive CLI (src.main) by default,
or to the MCP orchestrator pipeline (src.launch.main) with --orchestrator.
"""

import argparse
import sys


def entry():
    parser = argparse.ArgumentParser(
        description="Artemis City — Agentic Governance Platform",
    )
    parser.add_argument(
        "--orchestrator",
        action="store_true",
        help="Run the MCP orchestrator pipeline instead of the interactive CLI.",
    )
    args, remaining = parser.parse_known_args()

    # Restore remaining args so the sub-module's argparse sees them
    sys.argv = [sys.argv[0]] + remaining

    if args.orchestrator:
        from src.launch.main import main
    else:
        from src.main import main

    main()


if __name__ == "__main__":
    entry()
