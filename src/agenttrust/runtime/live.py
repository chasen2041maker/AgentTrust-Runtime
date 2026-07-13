"""Minimal live adapter for MVP evidence."""

from __future__ import annotations

from pathlib import Path

from agenttrust.application.run_tool import RunToolUseCase
from agenttrust.runtime.fixtures import RunResult, create_run_id
from agenttrust.runtime.gateway import ToolGateway
from agenttrust.runtime.trace import TraceRecorder
from agenttrust.permissions import PathSandbox, PermissionEngine, evaluate_pre_tool_hooks, finalize_permission, load_policy
from agenttrust.schemas import ToolIntent
from agenttrust.groundguard_adapter import map_tool_result, write_facts


def run_live(name: str, project_root: Path, runtime_mode: str = "interactive") -> RunResult:
    if name != "fake_tool_request":
        raise ValueError("unknown live adapter request. Available: fake_tool_request")

    run_id = create_run_id()
    run_dir = project_root / ".agenttrust" / "runs" / run_id
    recorder = TraceRecorder(run_dir)
    gateway = ToolGateway()
    permission_engine = PermissionEngine(load_policy(project_root / ".agenttrust" / "policy.yaml"))
    sandbox = PathSandbox(project_root)
    tool_runner = RunToolUseCase(
        evidence=recorder,
        policy_evaluator=permission_engine,
        sandbox=sandbox,
        tool_executor=gateway,
        finalize_permission=finalize_permission,
        evaluate_hooks=evaluate_pre_tool_hooks,
        map_facts=map_tool_result,
        store_facts=write_facts,
    )

    recorder.append("run_started", run_id=run_id, source="live_adapter", adapter=name, runtime_mode=runtime_mode)
    intent = ToolIntent(
        run_id=run_id,
        tool_call_id="call_001",
        tool_name="read_file",
        arguments={"path": "README.md"},
        source="live_adapter",
        runtime_mode=runtime_mode,
    )
    tool_runner.execute(
        intent,
        project_root=project_root,
        run_dir=run_dir,
        runtime_mode=runtime_mode,
        facts_path=run_dir / "facts.jsonl",
    )

    recorder.append("run_completed", run_id=run_id, status="completed")
    return RunResult(run_id=run_id, run_dir=run_dir, trace_path=recorder.trace_path)
