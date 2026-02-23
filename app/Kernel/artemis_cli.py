"""Artemis City Kernel Command-Line Interface Module.

This module implements the CLI entry point for the Artemis City agentic governance
system. It provides both single-command execution and interactive mode for ongoing
conversations with the kernel system.

The CLI initializes the kernel, processes commands, and executes plan files when
specified. In interactive mode, users can issue commands and receive responses
until they choose to exit.

Typical usage example:
    python app/Kernel/artemis_cli.py              # Interactive mode
    python app/Kernel/artemis_cli.py "status"     # Single command mode
    python app/Kernel/artemis_cli.py --plan plan.json  # Execute plan file

Dependencies:
    - argparse: Command-line argument parsing
    - sys: System-specific parameters and functions

Version: 1.0.0
License: MIT
"""

import argparse
import sys

from .kernel import Kernel


def main():
    """Entry point for the Artemis City Kernel CLI application.

    Parses command-line arguments, initializes the kernel, and either executes
    a single command/plan or enters interactive mode for ongoing command processing.

    In interactive mode, the CLI presents a prompt (artemis-cli>) and continuously
    processes user commands until exit is requested. Single-command mode executes
    one command and exits. Plan mode executes a predefined plan file.

    Args:
        None. Command-line arguments are parsed from sys.argv:
            - command (str, optional): Command string to execute in single-shot mode.
            - --plan (str, optional): Path to a plan file to execute.

    Returns:
        None. Function does not return; exits via sys.exit() on fatal errors.

    Raises:
        SystemExit: Exits with code 1 if kernel initialization fails.

    Side Effects:
        - Prints CLI output and responses to stdout
        - Reads user input from stdin in interactive mode
        - Initializes and runs the Kernel system

    Example:
        >>> # Run interactively
        >>> main()
        Welcome to Artemis-City CLI (Kernel v1.0)
        Type 'exit' to quit.
        artemis-cli> status
        [Kernel response...]
    """
    parser = argparse.ArgumentParser(description="Artemis-City Kernel CLI")
    parser.add_argument("command", nargs="?", help="The command string to execute")
    parser.add_argument("--plan", help="Path to a plan file to execute")

    args = parser.parse_args()

    # Initialize Kernel
    try:
        kernel = Kernel()
    except Exception as e:
        print(f"Fatal: Kernel failed to boot. {e}")
        sys.exit(1)

    if args.command:
        # One-shot command
        request = {"type": "command", "content": args.command}
        result = kernel.process(request)
        print(result)
    elif args.plan:
        # Execute plan
        request = {"type": "exec", "path": args.plan}
        result = kernel.process(request)
        print(result)
    else:
        # Interactive mode
        print("Welcome to Artemis-City CLI (Kernel v1.0)")
        print("Type 'exit' to quit.")
        while True:
            try:
                cmd = input("artemis-cli> ")
                if cmd.strip().lower() in ["exit", "quit"]:
                    break
                if not cmd.strip():
                    continue

                request = {"type": "command", "content": cmd}
                result = kernel.process(request)
                print(result)
            except KeyboardInterrupt:
                print("\nGoodbye.")
                break
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    main()
