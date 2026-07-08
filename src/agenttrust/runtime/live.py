"""Minimal live adapter for MVP evidence."""

from __future__ import annotations

from pathlib import Path

from agenttrust.runtime.fixtures import RunResult, create_run_id
from agenttrust.runtime.gateway import ToolGateway
from agenttrust.runtime.trace import TraceRecorder
from agenttrust.permissions import PathSandbox, PermissionEngine, finalize_permission, load_policy
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

    recorder.append("run_started", run_id=run_id, source="live_adapter", adapter=name, runtime_mode=runtime_mode)
    intent = ToolIntent(
        run_id=run_id,
        tool_call_id="call_001",
        tool_name="read_file",
        arguments={"path": "README.md"},
        source="live_adapter",
        runtime_mode=runtime_mode,
    )
    recorder.append("tool_intent", **intent.to_dict())

    permission_decision = permission_engine.decide(intent)
    final_permission = finalize_permission(permission_decision, runtime_mode)
    permission_event = {
        **permission_decision.to_dict(),
        **final_permission.to_dict(),
        "runtime_mode": runtime_mode,
    }
    recorder.append("permission_decision", **permission_event)
    if final_permission.final_effect == "allow":
        sandbox_decision = sandbox.check(intent)
        recorder.append("sandbox_decision", **sandbox_decision.to_dict())
        if sandbox_decision.effect == "allow":
            result = gateway.execute(intent, project_root)
            recorder.append("tool_result", **result.to_dict())
            facts = map_tool_result(result)
            if facts:
                write_facts(run_dir / "facts.jsonl", facts)
            recorder.append(
                "fact_mapped",
                run_id=run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                fact_count=len(facts),
                facts=[fact.to_dict() for fact in facts],
            )

    recorder.append("run_completed", run_id=run_id, status="completed")
    return RunResult(run_id=run_id, run_dir=run_dir, trace_path=recorder.trace_path)
