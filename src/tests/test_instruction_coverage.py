"""Behavior coverage for hierarchical instruction loading and caching."""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock

import pytest

from src.core.instructions import instruction_cache
from src.core.instructions.instruction_cache import InstructionCache
from src.core.instructions.instruction_loader import (
    InstructionLoader,
    InstructionScope,
    InstructionSet,
)


def test_instruction_set_orders_merges_and_renders_scopes() -> None:
    instructions = InstructionSet()
    assert instructions.get_merged() == ""

    high = InstructionScope("agent", "/agent.md", "agent rules", 4)
    low = InstructionScope("global", "/global.md", "global rules", 1)
    instructions.add_scope(high)
    instructions.add_scope(low)

    assert instructions.scopes == [low, high]
    assert (
        instructions.get_merged(include_markers=False) == "global rules\n\nagent rules"
    )
    assert "Instructions from global" in instructions.get_merged()
    assert str(low) == "[global] /global.md (priority: 1)"
    assert "InstructionSet with 2 scopes" in str(instructions)


def test_loader_reads_all_hierarchical_scopes(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    local = project / "feature"
    agent = project / "agents" / "reviewer"
    local.mkdir(parents=True)
    agent.mkdir(parents=True)
    global_file = tmp_path / "global.md"
    global_file.write_text("global")
    (project / "WARP.md").write_text("project")
    (local / "instructions.md").write_text("local")
    (agent / "reviewer.md").write_text("agent")

    loader = InstructionLoader(str(project))
    monkeypatch.setattr(loader, "GLOBAL_FILES", [str(global_file)])
    result = loader.load(str(local), "reviewer")

    assert [scope.level for scope in result.scopes] == [
        "global",
        "project",
        "local",
        "agent:reviewer",
    ]
    assert result.metadata == {
        "project_root": str(project.resolve()),
        "current_dir": str(local),
        "agent_name": "reviewer",
        "scope_count": 4,
    }
    assert loader.get_active_scopes(str(local))[:3] == [
        str(global_file),
        str(project / "WARP.md"),
        str(local / "instructions.md"),
    ]


def test_loader_skips_local_at_project_root_and_handles_no_project(tmp_path) -> None:
    (tmp_path / "instructions.md").write_text("local-looking")
    loader = InstructionLoader(str(tmp_path))
    loader.GLOBAL_FILES = []
    loader.PROJECT_FILES = []

    result = loader.load(str(tmp_path))
    assert result.scopes == []

    loader.project_root = None
    assert loader._load_project_instructions() is None
    assert loader._load_agent_instructions("reviewer") is None


def test_loader_read_file_and_project_discovery_fail_safely(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert InstructionLoader._read_file(str(tmp_path / "missing")) is None
    assert InstructionLoader._read_file(str(tmp_path)) is None

    path = tmp_path / "rules.md"
    path.write_text("rules")
    real_open = builtins.open

    def fail_open(file, *args, **kwargs):
        if str(file) == str(path):
            raise OSError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_open)
    assert InstructionLoader._read_file(str(path)) is None

    assert InstructionLoader._find_project_root(str(tmp_path)) == str(
        tmp_path.resolve()
    )
    project = tmp_path / "auto"
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]")
    monkeypatch.chdir(nested)
    assert InstructionLoader._find_project_root() == str(project)

    isolated = tmp_path / "isolated" / "nested"
    isolated.mkdir(parents=True)
    monkeypatch.chdir(isolated)
    (tmp_path / "auto" / "pyproject.toml").unlink()
    assert InstructionLoader._find_project_root() is None


def test_cache_hit_expiry_force_reload_stats_and_mutations(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = InstructionCache(ttl_seconds=10)
    first = InstructionSet(metadata={"version": 1})
    second = InstructionSet(metadata={"version": 2})
    third = InstructionSet(metadata={"version": 3})
    cache._loader.load = MagicMock(side_effect=[first, second, third])
    clock = iter([0.0, 1.0, 20.0, 20.0, 21.0, 21.0, 21.0])
    monkeypatch.setattr(instruction_cache.time, "time", lambda: next(clock))

    assert cache.get(str(tmp_path), "agent") is first
    assert cache.get(str(tmp_path), "agent") is first
    assert cache.get(str(tmp_path), "agent") is second
    assert cache.get(str(tmp_path), "agent", force_reload=True) is third
    stats = cache.get_stats()
    assert stats == {
        "total_entries": 1,
        "valid_entries": 1,
        "expired_entries": 0,
        "ttl_seconds": 10,
    }

    cache.invalidate(str(tmp_path), "agent")
    assert cache._cache == {}
    cache.invalidate(str(tmp_path), "missing")
    cache._cache["manual"] = (first, 0.0)
    cache.clear()
    assert cache._cache == {}


def test_cache_defaults_to_cwd_and_normalizes_keys(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = InstructionCache()
    loaded = InstructionSet()
    cache._loader.load = MagicMock(return_value=loaded)
    monkeypatch.chdir(tmp_path)

    assert cache.get() is loaded
    assert cache._make_cache_key(f"{tmp_path}/.", None) == f"{tmp_path}:_default"
    cache.invalidate()
    assert cache._cache == {}


def test_global_cache_lifecycle() -> None:
    instruction_cache.reset_global_cache()
    first = instruction_cache.get_global_cache(ttl_seconds=7)
    second = instruction_cache.get_global_cache(ttl_seconds=99)
    assert first is second
    assert first.ttl_seconds == 7

    first._cache["entry"] = (InstructionSet(), 0.0)
    instruction_cache.reset_global_cache()
    assert first._cache == {}
    assert instruction_cache._global_cache is None
