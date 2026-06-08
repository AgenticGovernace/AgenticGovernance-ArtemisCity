"""Compatibility entry point for the Artemis City kernel CLI.

The maintained implementation lives in :mod:`app.kernel.artemis_cli`. This
module keeps ``python -m app.kernel.cli`` and historical imports working.
"""

from app.kernel.artemis_cli import main

if __name__ == "__main__":
    main()
