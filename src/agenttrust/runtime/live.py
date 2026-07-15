"""Minimal live adapter for MVP evidence."""

from __future__ import annotations

import os
from pathlib import Path

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.policy.yaml_policy import snapshot_policy
from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.adapters.tools.gateway import ToolGateway
from agenttrust.groundguard_adapter import verify_answer, write_coverage_report
from agenttrust.application.run_tool import RunToolUseCase
from agenttrust.runtime.fixtures import RunResult, create_run_id
from agenttrust.permissions import PermissionEngine, evaluate_pre_tool_hooks, finalize_permission, load_policy
from agenttrust.schemas import ToolIntent
from agenttrust.adapters.verification.mapper import Fact, map_tool_result, write_facts


def run_live(name: str, project_root: Path, runtime_mode: str = "interactive") -> RunResult:
    if name != "fake_tool_request":
        raise ValueError("unknown live adapter request. Available: fake_tool_request")

    run_id = create_run_id()
    run_dir = project_root / ".agenttrust" / "runs" / run_id
    recorder = TraceRecorder(run_dir)
    gateway = ToolGateway()
    permission_engine = PermissionEngine(load_policy(project_root / ".agenttrust" / "policy.yaml"))
    sandbox = PathSandbox(project_root)
    snapshot_path, policy_version = snapshot_policy(project_root / ".agenttrust" / "policy.yaml", run_dir)
    recorder.bind(
        actor_id=os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
        agent_id=os.environ.get("AGENTTRUST_AGENT_ID"),
        session_id=os.environ.get("AGENTTRUST_SESSION_ID"),
        policy_version=policy_version,
    )
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

    recorder.append(
        "run_started",
        run_id=run_id,
        source="live_adapter",
        adapter=name,
        runtime_mode=runtime_mode,
        actor_id=os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
        agent_id=os.environ.get("AGENTTRUST_AGENT_ID"),
        session_id=os.environ.get("AGENTTRUST_SESSION_ID"),
    )
    recorder.append("policy_snapshot", run_id=run_id, policy_version=policy_version, path=str(snapshot_path))
    intent = ToolIntent(
        run_id=run_id,
        tool_call_id="call_001",
        tool_name="read_file",
        arguments={"path": "README.md"},
        source="live_adapter",
        runtime_mode=runtime_mode,
    )
    outcome = tool_runner.execute(
        intent,
        project_root=project_root,
        run_dir=run_dir,
        runtime_mode=runtime_mode,
        facts_path=run_dir / "facts.jsonl",
    )

    facts = tuple(fact for fact in outcome.facts if isinstance(fact, Fact))
    line_fact = next((fact for fact in facts if fact.key == "read_file_lines"), None)
    if line_fact is not None:
        answer = f"README.md has {line_fact.value} lines [fact:read_file_lines]."
        (run_dir / "final-answer.md").write_text(answer, encoding="utf-8")
        recorder.append("final_answer", run_id=run_id, answer=answer)
        coverage_report = verify_answer(
            answer,
            list(facts),
            ["read_file_lines"],
            session_id=run_id,
            verification_mode=permission_engine.policy.verification_mode,
        )
        write_coverage_report(run_dir / "groundguard-report.json", coverage_report)
        recorder.append("groundguard_check", run_id=run_id, **coverage_report.to_dict())

    recorder.append("run_completed", run_id=run_id, status="completed")
    return RunResult(run_id=run_id, run_dir=run_dir, trace_path=recorder.trace_path)
