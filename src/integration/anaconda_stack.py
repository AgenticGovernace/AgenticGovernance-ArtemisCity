"""Register the Anaconda Agent Studio stack into the Artemis AgentRegistry.

Brings the six-agent stack at ``~/Source/artemis-agent-stack/`` —
discovered via Anaconda Desktop's ``/api/agents/v1/models`` endpoint —
into Artemis-City's :class:`AgentRegistry` so capability-based routing
naturally finds them.

The mapping is opt-in.  Only agents whose port is configured via
``ANACONDA_AGENT_PORTS`` get registered, because Agent Studio's
discovery endpoint does not surface ports.  Set ports from each agent's
**Connection Info → Runtime root** URL.

Usage at orchestrator startup:

.. code-block:: python

    from src.integration.anaconda_stack import register_anaconda_stack

    registered = register_anaconda_stack(self.registry)
    logger.info("Anaconda agents registered: %s", registered)
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from src.integration.anaconda_agent_proxy import (
    ANACONDA_API_KEY_ENV,
    DEFAULT_ANACONDA_API_KEY,
    AnacondaAgentProxy,
    discover_anaconda_agents,
    parse_port_map,
)

logger = logging.getLogger(__name__)


# Default capability sets per Anaconda agent.  Aligns with the BUILD_NOTE
# under ~/Source/artemis-agent-stack/: Oracle routes, Compsuite audits,
# Packrat archives, Compressor distills, Loki writes.  Callers can override
# any subset via the capability_overrides argument.
DEFAULT_CAPABILITIES: Dict[str, List[str]] = {
    "artemis-oracle": ["orchestration", "atp_routing", "reflective_synthesis"],
    "artemis-compsuite": ["audit", "atp_validation", "provenance_review"],
    "artemis-packrat": ["archive", "tag", "search"],
    "artemis-compressor": ["summarization", "compression"],
    "artemis-loki": ["code_write", "git", "refactor"],
}


def register_anaconda_stack(
    registry,
    *,
    capability_overrides: Optional[Dict[str, List[str]]] = None,
    port_map_env: str = "ANACONDA_AGENT_PORTS",
    skip_discovery: bool = False,
    api_key: Optional[str] = None,
) -> List[str]:
    """Discover running Anaconda agents and register them with ``registry``.

    Args:
        registry: Anything with a ``register_agent(BaseAgent)`` method.
            In the live system this is :class:`AgentRegistry`; the tests
            stub it.
        capability_overrides: Per-agent overrides merged onto
            :data:`DEFAULT_CAPABILITIES`.  Useful for downgrading
            capabilities in a constrained environment (e.g. removing
            ``code_write`` from Loki on a CI sandbox).
        port_map_env: Name of the env var holding the port map.  Defaults
            to ``ANACONDA_AGENT_PORTS``.
        skip_discovery: When ``True``, register every port-mapped agent
            without first verifying it's reported by Anaconda Desktop.
            Useful for offline / CI runs.
        api_key: Bearer token used for both discovery and per-agent
            requests.  Caller > ``ANACONDA_API_KEY`` env > permissive
            default ``*`` (matches Anaconda Agent Studio Beta).

    Returns:
        List of agent names that were successfully registered.  Agents
        whose port is mapped but who are not reported by discovery (or
        whose registration raises) are skipped with a warning.
    """
    caps = {**DEFAULT_CAPABILITIES, **(capability_overrides or {})}
    port_map = parse_port_map(os.getenv(port_map_env, ""))
    if not port_map:
        logger.info(
            "%s is empty; no Anaconda Agent Studio agents will be registered.",
            port_map_env,
        )
        return []

    resolved_key = api_key if api_key is not None else os.getenv(ANACONDA_API_KEY_ENV)
    bearer = resolved_key if resolved_key else DEFAULT_ANACONDA_API_KEY

    if skip_discovery:
        running = set(port_map.keys())
    else:
        discovered = discover_anaconda_agents(api_key=bearer)
        running = {m["id"] for m in discovered if isinstance(m.get("id"), str)}
        if not running:
            logger.warning(
                "Anaconda Desktop reported no artemiscity-provider agents. "
                "Is Agent Studio running? Skipping registration."
            )
            return []

    registered: List[str] = []
    for name, port in port_map.items():
        if name not in running:
            logger.warning(
                "Agent %r in %s is not currently reported by Anaconda Desktop. "
                "Skipping registration.",
                name,
                port_map_env,
            )
            continue
        proxy = AnacondaAgentProxy(
            name=name,
            port=port,
            capabilities=caps.get(name, ["llm_chat"]),
            api_key=bearer,
        )
        try:
            registry.register_agent(proxy)
            registered.append(name)
            logger.info(
                "Registered Anaconda agent proxy: %s on port %d (capabilities=%s)",
                name,
                port,
                proxy.capabilities,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to register %r: %s", name, exc)
    return registered
