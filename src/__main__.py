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
        add_help=False,
    )
    # Wrapper-level toggles for which sub-module to invoke
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

    help_requested = any(arg in ("-h", "--help") for arg in remaining)
    remaining_without_help = [
        arg for arg in remaining if arg not in ("-h", "--help")
    ]

    # Decide how to handle help:
    # - If help is requested *and* we have not selected a specific mode
    #   and there are no additional args, show the wrapper help.
    # - Otherwise, forward a help flag to the selected sub-module so its
    #   own argparse can display detailed help.
    forwarded_args = list(remaining_without_help)
    if (
        help_requested
        and not args.orchestrator
        and not args.atp
        and not remaining_without_help
    ):
        parser.print_help()
        sys.exit(0)
    elif help_requested:
        # User requested help in combination with a mode or extra args:
        # forward --help to the underlying module.
        forwarded_args.append("--help")

    # Restore remaining args (plus possibly forwarded --help) so the
    # sub-module's argparse sees them.
    sys.argv = [sys.argv[0]] + forwarded_args

    if args.orchestrator:
        from src.launch.main import main
    elif args.atp:
        from src.main import main
    else:
        from src.Kernel.artemis_cli import main

    main()


if __name__ == "__main__":
    entry()
