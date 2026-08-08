"""Entrypoint so `python -m relay` runs the dispatcher."""

from .agent import main

if __name__ == "__main__":
    raise SystemExit(main())
