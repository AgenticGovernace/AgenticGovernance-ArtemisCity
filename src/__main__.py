"""Package entry point for Artemis City.

Enables running the project as a module:

    python -m src                          # Interactive Kernel CLI (default)
    python -m src --orchestrator           # MCP orchestrator pipeline
    python -m src --atp                    # ATP-enabled CLI
    python -m src "status"                 # One-shot Kernel command
    python -m src --plan plan.json         # Execute a plan file
"""

import argparse
import sys


def entry():
    # Peek at args to decide which sub-CLI to dispatch to.
    # --orchestrator and --atp are consumed here; everything else
    # is forwarded to the chosen sub-module's own argparse.
    parser = argparse.ArgumentParser(
        description="Artemis City — Agentic Governance Platform",
    )
    parser.add_argument(
        "--orchestrator",
        action="store_true",
        help="Run the MCP orchestrator pipeline.",
    )
    parser.add_argument(
        "--atp",
        action="store_true",
        help="Run the ATP (Artemis Transmission Protocol) CLI.",
    )
    args, remaining = parser.parse_known_args()

    # Restore remaining args so the sub-module's argparse sees them
    sys.argv = [sys.argv[0]] + remaining

    if args.orchestrator:
        from src.launch.main import main
    elif args.atp:
        from src.main import main
    else:
        from src.Kernel.artemis_cli import main

    main()


if __name__ == "__main__":
    entry()
