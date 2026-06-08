"""Repo-root compatibility package for legacy ``memory.*`` imports.

The canonical Artemis City implementation lives under ``src.integration``.
This shim exists so repo-root commands such as ``python -c 'from
memory.integration import MemoryClient'`` work even when ``src/`` is not on
``sys.path`` as a top-level package root.
"""

