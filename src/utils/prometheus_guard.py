"""Re-import-safe Prometheus metric creation.

Prometheus' default CollectorRegistry rejects duplicate registrations,
which crashes a module's import when its module-level metric declarations
are loaded twice — common during tests that do ``sys.modules.pop`` +
re-import, or ``importlib.reload``. Use :func:`safe_metric` at module
load so reimport returns the already-registered collector instead of
raising ``ValueError: Duplicated timeseries in CollectorRegistry``.
"""

from __future__ import annotations

try:
    from prometheus_client import REGISTRY

    METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    METRICS_AVAILABLE = False
    REGISTRY = None  # type: ignore


def safe_metric(cls, name, *args, **kwargs):
    """Create a Prometheus metric, returning the existing one on re-import.

    ``cls`` is the metric class (``Counter``, ``Gauge``, ``Histogram``,
    ``Summary``); remaining args mirror that class's constructor. Looks
    up against the default ``REGISTRY`` only.

    Args:
        name: Name of the item, class, or environment to resolve.
        *args: Parsed command-line arguments for the current invocation.
        **kwargs: Kwargs value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    try:
        return cls(name, *args, **kwargs)
    except ValueError:
        # _names_to_collectors maps every child timeseries name back to
        # its parent collector — stable in prometheus_client since 0.6.
        return REGISTRY._names_to_collectors[name]
