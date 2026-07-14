"""Smoke tests for the app/kernel package (Phase A of #67).

These guard the de-Daemon'd kernel layer: previously ``app/kernel/kernel.py``
imported from a nonexistent ``Daemon.*`` package and referenced undefined
``DaemonAgent`` / ``PlannerAgent`` classes, so ``import app.kernel.kernel``
raised ``ModuleNotFoundError``. The tests below ensure the package imports
cleanly, boots, routes to the de-Daemon'd agents, and carries no leftover
``Daemon`` identifiers in importable code.
"""

import importlib


def test_kernel_package_modules_import():
    """Every module in app/kernel imports without error.

    Returns:
        None: This function does not return a value.
    """
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
    """Kernel() boots all subsystems without writing into the repo tree.

    Args:
        tmp_path: Tmp path value used by this operation.
        monkeypatch: Monkeypatch value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    kernel = Kernel(
        state_file=str(tmp_path / "state_kernel.json"),
        memory_path=str(tmp_path / "memory_store"),
    )
    assert kernel.booted is True
    assert kernel.router is not None
    assert kernel.memory is not None


def test_default_route_uses_daemon_agent(tmp_path, monkeypatch):
    """System/unmatched commands fall through to the daemon agent.

    Args:
        tmp_path: Tmp path value used by this operation.
        monkeypatch: Monkeypatch value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    result = Kernel(
        state_file=str(tmp_path / "state_kernel.json"),
        memory_path=str(tmp_path / "memory_store"),
    ).process({"type": "command", "content": "system status"})
    assert "daemon" in result.lower()
    assert "codex" not in result.lower()


def test_planner_route_uses_planner_agent(tmp_path, monkeypatch):
    """Planning keywords route to the planner agent.

    Args:
        tmp_path: Tmp path value used by this operation.
        monkeypatch: Monkeypatch value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    result = Kernel(
        state_file=str(tmp_path / "state_kernel.json"),
        memory_path=str(tmp_path / "memory_store"),
    ).process({"type": "command", "content": "draft a roadmap"})
    assert "planner" in result


def test_router_default_is_daemon() -> None:
    """The router's fallback agent is the lowercase ``daemon`` id.

    Returns:
        None: This function does not return a value.
    """
    from app.kernel.agent_router import AgentRouter

    route = AgentRouter().route("zzzqqq no keywords here")
    assert route["agent"] == "daemon"


def test_unimplemented_persona_route_falls_back_to_daemon(tmp_path, monkeypatch):
    """Routes declared in YAML but lacking a concrete agent (artemis/
    pack_rat/copilot) are handled by the daemon, and the response reports
    the actual handler rather than the routed persona name.

    Args:
        tmp_path: Tmp path value used by this operation.
        monkeypatch: Monkeypatch value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    monkeypatch.chdir(tmp_path)
    from app.kernel.kernel import Kernel

    # "governance review" matches the artemis route, which has no concrete
    # agent yet (Phase B of #67) -> must be handled by the daemon.
    result = Kernel(
        state_file=str(tmp_path / "state_kernel.json"),
        memory_path=str(tmp_path / "memory_store"),
    ).process({"type": "command", "content": "governance review"})
    assert "[Kernel] daemon responded:" in result
    assert "artemis" not in result
