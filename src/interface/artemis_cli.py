"""Compatibility entry point for the Artemis City kernel CLI.

The maintained implementation lives in :mod:`app.kernel.cli`. This wrapper
keeps the historical ``src.interface.artemis_cli`` module importable while
avoiding duplicate CLI logic.
"""

from app.kernel.cli import main


if __name__ == "__main__":
    main()
