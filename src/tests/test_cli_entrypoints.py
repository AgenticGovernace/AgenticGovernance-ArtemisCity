"""Behavioral tests for the maintained Artemis City command-line entry points.

The CLIs sit at integration boundaries, so these tests replace the vault,
orchestrator, and kernel while retaining the real argument parsing and dispatch
logic.  This keeps the suite deterministic without reducing the checks to
import-only smoke tests.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

import src
from app.kernel import artemis_cli as kernel_cli
from src.launch import main as launch_main


def _launch_args(**overrides) -> SimpleNamespace:
    """Return a complete argument namespace for ``src.launch.main`` tests."""
    values = {
        "instruction": None,
        "capability": None,
        "agent": None,
        "title": None,
        "skip_demos": True,
        "show_hebbian": False,
        "agent_stats": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _mock_launch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    args: SimpleNamespace,
    *,
    vault_exists: bool = True,
) -> tuple[MagicMock, MagicMock]:
    """Install isolated launch dependencies and return orchestrator/run logger."""
    orchestrator = MagicMock(name="orchestrator")
    orchestrator.agent_registry.get_agent_names.return_value = ["Research Agent"]
    orchestrator.check_for_new_tasks_from_obsidian.return_value = []
    run_logger = MagicMock(name="run_logger")
    run_logger.md_path = Path("run.md")

    monkeypatch.setattr(launch_main, "parse_cli_args", lambda: args)
    monkeypatch.setattr(launch_main, "init_run_logger", lambda: run_logger)
    monkeypatch.setattr(launch_main.os.path, "exists", lambda _path: vault_exists)
    monkeypatch.setattr(
        launch_main.src.mcp.orchestrator,
        "Orchestrator",
        MagicMock(return_value=orchestrator),
    )
    return orchestrator, run_logger


def test_parse_cli_args_accepts_all_supported_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator CLI should preserve every explicit user selection."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "artemis",
            "--instruction",
            "summarize this",
            "--capability",
            "text_summarization",
            "--agent",
            "summarizer_agent",
            "--title",
            "Brief",
            "--skip-demos",
            "--show-hebbian",
            "--agent-stats",
            "research_agent",
        ],
    )

    args = launch_main.parse_cli_args()

    assert vars(args) == {
        "instruction": "summarize this",
        "capability": "text_summarization",
        "agent": "summarizer_agent",
        "title": "Brief",
        "skip_demos": True,
        "show_hebbian": True,
        "agent_stats": "research_agent",
    }


def test_launch_script_bootstraps_repo_root_on_sys_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct script execution should make absolute ``src`` imports available."""
    script_path = Path(launch_main.__file__).resolve()
    project_root = str(script_path.parents[2])
    monkeypatch.setattr(
        sys, "path", [entry for entry in sys.path if entry != project_root]
    )

    runpy.run_path(str(script_path), run_name="cli_bootstrap_probe")

    assert sys.path[0] == project_root


def test_setup_example_task_note_leaves_existing_note_untouched(tmp_path) -> None:
    """Demo setup must be idempotent when the example note already exists."""
    existing = tmp_path / "Example Research Task.md"
    existing.write_text("already present")
    obs_manager = MagicMock()
    obs_manager._get_full_path.return_value = existing
    memory_bus = MagicMock()

    launch_main.setup_example_task_note(obs_manager, memory_bus)

    memory_bus.write_note_with_embedding.assert_not_called()
    obs_manager.write_note.assert_not_called()


def test_setup_example_task_note_writes_through_memory_bus(tmp_path) -> None:
    """New demo content should use the governed memory write-through path."""
    obs_manager = MagicMock()
    obs_manager._get_full_path.return_value = tmp_path / "missing.md"
    memory_bus = MagicMock()

    launch_main.setup_example_task_note(obs_manager, memory_bus)

    relative_path, content = memory_bus.write_note_with_embedding.call_args.args[:2]
    assert relative_path.endswith("Example Research Task.md")
    assert "required_capability: web_search" in content
    assert "# Research Task: Artificial Intelligence Ethics" in content
    assert memory_bus.write_note_with_embedding.call_args.kwargs == {
        "metadata": {"demo": True},
        "embed": True,
    }
    obs_manager.write_note.assert_not_called()


def test_setup_example_task_note_falls_back_when_memory_bus_fails(tmp_path) -> None:
    """A memory-bus outage should still leave the human-readable task note."""
    obs_manager = MagicMock()
    obs_manager._get_full_path.return_value = tmp_path / "missing.md"
    memory_bus = MagicMock()
    memory_bus.write_note_with_embedding.side_effect = RuntimeError("offline")

    launch_main.setup_example_task_note(obs_manager, memory_bus)

    relative_path, content = obs_manager.write_note.call_args.args
    assert relative_path.endswith("Example Research Task.md")
    assert "task_id:" in content
    assert obs_manager.write_note.call_args.kwargs == {"overwrite": False}


def test_setup_example_task_note_can_write_without_memory_bus(tmp_path) -> None:
    """Standalone launch remains usable when no memory bus was constructed."""
    obs_manager = MagicMock()
    obs_manager._get_full_path.return_value = tmp_path / "missing.md"

    launch_main.setup_example_task_note(obs_manager)

    obs_manager.write_note.assert_called_once()
    assert obs_manager.write_note.call_args.kwargs == {"overwrite": False}


def test_handle_user_instruction_ignores_blank_text() -> None:
    """Whitespace-only input should not create or dispatch a task."""
    orchestrator = MagicMock()

    launch_main.handle_user_instruction(orchestrator, "  \n", None)

    orchestrator.create_new_task_in_obsidian.assert_not_called()
    orchestrator.route_and_execute_task.assert_not_called()


def test_handle_user_instruction_dispatches_to_pinned_agent() -> None:
    """An explicit agent should bypass routing and derive its first capability."""
    orchestrator = MagicMock()
    agent = SimpleNamespace(name="Research Agent", capabilities=["web_search"])
    orchestrator.agent_registry.get_agent.return_value = agent
    orchestrator.create_new_task_in_obsidian.return_value = "Agent Inputs/task.md"

    launch_main.handle_user_instruction(
        orchestrator,
        "Research current governance patterns",
        None,
        agent_name="research_agent",
    )

    orchestrator.agent_registry.get_agent.assert_called_once_with("Research Agent")
    task = orchestrator.create_new_task_in_obsidian.call_args.args[0]
    assert task["agent"] == "Research Agent"
    assert task["required_capability"] == "web_search"
    assert task["content"] == "Research current governance patterns"
    orchestrator.update_task_status_in_obsidian.assert_called_once_with(
        "Agent Inputs/task.md", "in progress", task["task_id"]
    )
    orchestrator.assign_and_execute_task.assert_called_once_with(
        "Research Agent", task, "Agent Inputs/task.md"
    )
    orchestrator.route_and_execute_task.assert_not_called()


def test_handle_user_instruction_routes_default_capability_after_note_failure() -> None:
    """Routing should continue with ``llm_chat`` if vault persistence is offline."""
    orchestrator = MagicMock()
    orchestrator.create_new_task_in_obsidian.side_effect = OSError("vault offline")

    launch_main.handle_user_instruction(
        orchestrator,
        "Explain the city status",
        None,
        title="Status explanation",
    )

    task = orchestrator.create_new_task_in_obsidian.call_args.args[0]
    assert task["title"] == "Status explanation"
    assert task["required_capability"] == "llm_chat"
    assert "agent" not in task
    orchestrator.route_and_execute_task.assert_called_once_with(task, None)
    orchestrator.update_task_status_in_obsidian.assert_not_called()


def test_handle_user_instruction_rejects_unknown_or_incapable_agent() -> None:
    """Pinned dispatch must fail closed for unknown and capability-less agents."""
    unknown = MagicMock()
    unknown.agent_registry.get_agent.return_value = None
    unknown.agent_registry.get_agent_names.return_value = ["Research Agent"]

    launch_main.handle_user_instruction(unknown, "Do work", None, agent_name="ghost")

    unknown.create_new_task_in_obsidian.assert_not_called()

    incapable = MagicMock()
    incapable.agent_registry.get_agent.return_value = SimpleNamespace(
        name="Empty Agent", capabilities=[]
    )

    launch_main.handle_user_instruction(
        incapable, "Do work", None, agent_name="Empty Agent"
    )

    incapable.create_new_task_in_obsidian.assert_not_called()


def test_handle_user_instruction_marks_persisted_task_failed_on_dispatch_error() -> (
    None
):
    """A failed routed execution should synchronize the persisted task status."""
    orchestrator = MagicMock()
    orchestrator.create_new_task_in_obsidian.return_value = "Agent Inputs/task.md"
    orchestrator.route_and_execute_task.side_effect = RuntimeError("agent crashed")

    launch_main.handle_user_instruction(orchestrator, "Do work", "reasoning")

    task = orchestrator.create_new_task_in_obsidian.call_args.args[0]
    assert orchestrator.update_task_status_in_obsidian.call_args_list == [
        call("Agent Inputs/task.md", "in progress", task["task_id"]),
        call("Agent Inputs/task.md", "failed", task["task_id"]),
    ]


def test_main_reports_missing_vault_and_does_not_boot_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launch should fail before boot when the configured vault is unavailable."""
    _orchestrator, run_logger = _mock_launch_runtime(
        monkeypatch, _launch_args(), vault_exists=False
    )
    constructor = launch_main.src.mcp.orchestrator.Orchestrator

    launch_main.main()

    constructor.assert_not_called()
    run_logger.finalize_run.assert_called_once_with(
        status="error", summary={"error": "vault_not_found"}
    )


@pytest.mark.parametrize(
    ("args", "method", "expected"),
    [
        (_launch_args(show_hebbian=True), "show_hebbian_network_summary", None),
        (
            _launch_args(agent_stats="research_agent"),
            "show_agent_hebbian_stats",
            "Research Agent",
        ),
    ],
)
def test_main_handles_hebbian_display_flags(
    monkeypatch: pytest.MonkeyPatch,
    args: SimpleNamespace,
    method: str,
    expected: str | None,
) -> None:
    """Hebbian inspection flags should invoke the requested view and exit early."""
    orchestrator, run_logger = _mock_launch_runtime(monkeypatch, args)

    launch_main.main()

    target = getattr(orchestrator, method)
    if expected is None:
        target.assert_called_once_with()
    else:
        target.assert_called_once_with(expected)
    orchestrator.check_for_new_tasks_from_obsidian.assert_not_called()
    run_logger.finalize_run.assert_not_called()


def test_main_default_run_skips_demos_and_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-demo default path should poll once and close its audit run."""
    orchestrator, run_logger = _mock_launch_runtime(monkeypatch, _launch_args())

    launch_main.main()

    orchestrator.check_for_new_tasks_from_obsidian.assert_called_once_with()
    run_logger.finalize_run.assert_called_once_with(
        status="completed",
        summary={
            "tasks_found": 0,
            "skip_demos": True,
            "instruction_provided": False,
        },
    )


def test_main_runs_demo_and_cli_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled demos and one-off instructions should both enter their workflows."""
    args = _launch_args(
        skip_demos=False,
        instruction="Summarize this",
        capability="text_summarization",
        title="Summary",
        agent="summarizer_agent",
    )
    orchestrator, run_logger = _mock_launch_runtime(monkeypatch, args)
    setup = MagicMock()
    handle = MagicMock()
    monkeypatch.setattr(launch_main, "setup_example_task_note", setup)
    monkeypatch.setattr(launch_main, "handle_user_instruction", handle)

    launch_main.main()

    setup.assert_called_once_with(orchestrator.obs_manager, orchestrator.memory_bus)
    orchestrator.route_and_execute_task.assert_called_once()
    direct_task = orchestrator.route_and_execute_task.call_args.args[0]
    assert direct_task["required_capability"] == "text_summarization"
    handle.assert_called_once_with(
        orchestrator,
        "Summarize this",
        "text_summarization",
        "Summary",
        "summarizer_agent",
    )
    run_logger.finalize_run.assert_called_once()


def test_main_continues_when_demo_routing_has_no_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optional demonstration must not prevent pending-task polling."""
    orchestrator, run_logger = _mock_launch_runtime(
        monkeypatch, _launch_args(skip_demos=False)
    )
    monkeypatch.setattr(launch_main, "setup_example_task_note", MagicMock())
    orchestrator.route_and_execute_task.side_effect = ValueError("no agent")

    launch_main.main()

    orchestrator.check_for_new_tasks_from_obsidian.assert_called_once_with()
    run_logger.finalize_run.assert_called_once()


def test_main_processes_pending_tasks_and_marks_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending tasks should transition to success, failure, or no-capability."""
    orchestrator, run_logger = _mock_launch_runtime(monkeypatch, _launch_args())
    good = {
        "task_id": "good-1",
        "title": "Good task",
        "required_capability": "web_search",
    }
    failed = {
        "task_id": "failed-1",
        "title": "Failed task",
        "required_capability": "reasoning",
    }
    incomplete = {"task_id": "missing-1", "title": "Missing capability"}
    orchestrator.check_for_new_tasks_from_obsidian.return_value = [
        ("good.md", good),
        ("failed.md", failed),
        ("incomplete.md", incomplete),
    ]
    orchestrator.route_and_execute_task.side_effect = [None, RuntimeError("boom")]

    launch_main.main()

    assert orchestrator.route_and_execute_task.call_args_list == [
        call(good, "good.md"),
        call(failed, "failed.md"),
    ]
    assert orchestrator.update_task_status_in_obsidian.call_args_list == [
        call("good.md", "in progress", "good-1"),
        call("failed.md", "in progress", "failed-1"),
        call("failed.md", "failed", "failed-1"),
        call("incomplete.md", "no_capability", "missing-1"),
    ]
    run_logger.finalize_run.assert_called_once_with(
        status="completed",
        summary={
            "tasks_found": 3,
            "skip_demos": True,
            "instruction_provided": False,
        },
    )


def test_src_entry_shows_wrapper_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare wrapper help should be handled without booting a sub-CLI."""
    monkeypatch.setattr(sys, "argv", ["python -m src", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        src.entry()

    assert exc_info.value.code == 0
    assert "Artemis City" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("wrapper_args", "target_module", "forwarded"),
    [
        (
            ["--orchestrator", "--skip-demos"],
            "src.launch.main",
            ["--skip-demos"],
        ),
        (["status"], "src.interface.artemis_cli", ["status"]),
        (
            ["--orchestrator", "--help"],
            "src.launch.main",
            ["--help"],
        ),
    ],
)
def test_src_entry_dispatches_and_forwards_arguments(
    monkeypatch: pytest.MonkeyPatch,
    wrapper_args: list[str],
    target_module: str,
    forwarded: list[str],
) -> None:
    """Wrapper-only switches should be consumed before the maintained CLI runs."""
    target = __import__(target_module, fromlist=["main"])
    sub_main = MagicMock()
    monkeypatch.setattr(target, "main", sub_main)
    monkeypatch.setattr(sys, "argv", ["python -m src", *wrapper_args])

    src.entry()

    sub_main.assert_called_once_with()
    assert sys.argv == ["python -m src", *forwarded]


def test_src_entry_rejects_atp_until_adapter_lands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reserved ATP wrapper must fail closed until its adapter exists."""
    ordinary_cli = MagicMock()
    monkeypatch.setattr("src.interface.artemis_cli.main", ordinary_cli)
    monkeypatch.setattr(sys, "argv", ["python -m src", "--atp", "status"])

    with pytest.raises(SystemExit) as exc_info:
        src.entry()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == (
        "--atp is reserved for the forthcoming Routing Kernel ATP adapter; "
        "use the default CLI or --orchestrator for now.\n"
    )
    ordinary_cli.assert_not_called()


def test_src_module_entrypoint_calls_package_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``python -m src`` should call the package's dispatch function exactly once."""
    dispatch = MagicMock()
    monkeypatch.setattr(src, "entry", dispatch)

    runpy.run_module("src.__main__", run_name="__main__")

    dispatch.assert_called_once_with()


def test_kernel_cli_executes_one_shot_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A positional command should become a kernel ``command`` request."""
    kernel = MagicMock()
    kernel.process.return_value = "daemon responded"
    monkeypatch.setattr(kernel_cli, "Kernel", MagicMock(return_value=kernel))
    monkeypatch.setattr(sys, "argv", ["artemis", "system status"])

    kernel_cli.main()

    kernel.process.assert_called_once_with(
        {"type": "command", "content": "system status"}
    )
    assert capsys.readouterr().out.strip() == "daemon responded"


def test_kernel_cli_executes_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plan path should become a kernel ``exec`` request."""
    kernel = MagicMock()
    kernel.process.return_value = "plan complete"
    monkeypatch.setattr(kernel_cli, "Kernel", MagicMock(return_value=kernel))
    monkeypatch.setattr(sys, "argv", ["artemis", "--plan", "plan.json"])

    kernel_cli.main()

    kernel.process.assert_called_once_with({"type": "exec", "path": "plan.json"})
    assert capsys.readouterr().out.strip() == "plan complete"


def test_kernel_cli_interactive_mode_skips_blanks_and_processes_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Interactive mode should ignore blank lines and stop on a quit command."""
    kernel = MagicMock()
    kernel.process.return_value = "planner responded"
    commands = iter(["   ", "draft a roadmap", "QUIT"])
    monkeypatch.setattr(kernel_cli, "Kernel", MagicMock(return_value=kernel))
    monkeypatch.setattr(sys, "argv", ["artemis"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))

    kernel_cli.main()

    kernel.process.assert_called_once_with(
        {"type": "command", "content": "draft a roadmap"}
    )
    output = capsys.readouterr().out
    assert "Welcome to Artemis-City Kernel" in output
    assert "planner responded" in output


def test_kernel_cli_interactive_mode_handles_interrupt_and_processing_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Interactive errors should be reported, while Ctrl-C exits cleanly."""
    kernel = MagicMock()
    kernel.process.side_effect = RuntimeError("bad command")
    inputs = iter(["bad", KeyboardInterrupt()])

    def next_input(_prompt: str) -> str:
        value = next(inputs)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(kernel_cli, "Kernel", MagicMock(return_value=kernel))
    monkeypatch.setattr(sys, "argv", ["artemis"])
    monkeypatch.setattr("builtins.input", next_input)

    kernel_cli.main()

    output = capsys.readouterr().out
    assert "Error: bad command" in output
    assert "Goodbye." in output


def test_kernel_cli_reports_boot_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kernel construction failures should produce a non-zero CLI exit."""
    monkeypatch.setattr(
        kernel_cli, "Kernel", MagicMock(side_effect=RuntimeError("state corrupt"))
    )
    monkeypatch.setattr(sys, "argv", ["artemis"])

    with pytest.raises(SystemExit) as exc_info:
        kernel_cli.main()

    assert exc_info.value.code == 1
    assert "Fatal: Kernel failed to boot. state corrupt" in capsys.readouterr().out
