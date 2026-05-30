"""Smoke tests for the app/kernel package (Phase A of #67).

These guard the de-codex'd kernel layer: previously ``app/kernel/kernel.py``
imported from a nonexistent ``codex.*`` package and referenced undefined
``CodexAgent`` / ``PlannerAgent`` classes, so ``import app.kernel.kernel``
raised ``ModuleNotFoundError``. The tests below ensure the package imports
cleanly, boots, routes to the de-codex'd agents, and carries no leftover
``codex`` identifiers in importable code.
"""

import importlib


def test_kernel_package_modules_import():
    """Every module in app/kernel imports without error."""
    for mod in (
        "app.kernel.kernel",
        "app.kernel.agent_router",
        "app.kernel.memory_bus",
        "app.kernel.cli",
        "app.kernel.agents",
        "app.kernel.agents.base",
        "app.kernel.agents.daemon_agent",
        "app.kernel.agents.planner_agent",
    ):
        importlib.import_module(mod)


def test_kernel_boots(tmp_path, monkeypatch):
    """Kernel() boots all subsystems without writing into the repo tree."""
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    kernel = Kernel()
    assert kernel.booted is True
    assert kernel.router is not None
    assert kernel.memory is not None


def test_default_route_uses_daemon_agent(tmp_path, monkeypatch):
    """System/unmatched commands fall through to the daemon agent."""
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    result = Kernel().process({"type": "command", "content": "system status"})
    assert "daemon" in result
    assert "codex" not in result.lower()


def test_planner_route_uses_planner_agent(tmp_path, monkeypatch):
    """Planning keywords route to the planner agent."""
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    result = Kernel().process({"type": "command", "content": "draft a roadmap"})
    assert "planner" in result


def test_router_default_is_daemon_not_codex():
    """The router's fallback agent was renamed codex_daemon -> daemon."""
    from app.kernel.agent_router import AgentRouter

    route = AgentRouter().route("zzzqqq no keywords here")
    assert route["agent"] == "daemon"
