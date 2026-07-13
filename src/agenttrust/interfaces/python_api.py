"""Python SDK entrypoint for framework-hosted agent loops."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.evidence.recovery import create_backup_for_write
from agenttrust.adapters.policy.yaml_policy import load_policy, snapshot_policy
from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.adapters.tools.gateway import ToolGateway
from agenttrust.adapters.verification.mapper import map_tool_result, write_facts
from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.models import ToolIntent
from agenttrust.permissions import PermissionEngine, evaluate_pre_tool_hooks, finalize_permission, request_interactive_approval
from agenttrust.runtime.fixtures import create_run_id


@dataclass(frozen=True)
class PythonRunResult:
    run_id: str
    run_dir: Path
    outcome: ToolRunOutcome


class AgentTrustRuntime:
    """Embed governed local tool execution inside a custom agent framework."""

    def __init__(self, project_root: Path, runtime_mode: str = "interactive") -> None:
        self.project_root = project_root.resolve()
        self.runtime_mode = runtime_mode

    def execute(self, tool_name: str, arguments: dict[str, object], source: str = "python_sdk") -> PythonRunResult:
        run_id = create_run_id()
        run_dir = self.project_root / ".agenttrust" / "runs" / run_id
        recorder = TraceRecorder(run_dir)
        policy_path = self.project_root / ".agenttrust" / "policy.yaml"
        policy = load_policy(policy_path)
        snapshot_path, policy_version = snapshot_policy(policy_path, run_dir)
        recorder.append(
            "run_started",
            run_id=run_id,
            source=source,
            runtime_mode=self.runtime_mode,
            actor_id=os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
            agent_id=os.environ.get("AGENTTRUST_AGENT_ID"),
            session_id=os.environ.get("AGENTTRUST_SESSION_ID"),
        )
        recorder.append("policy_snapshot", run_id=run_id, policy_version=policy_version, path=str(snapshot_path))
        intent = ToolIntent(
            run_id=run_id,
            tool_call_id="call_001",
            tool_name=tool_name,
            arguments=arguments,
            source=source,
            runtime_mode=self.runtime_mode,
        )
        outcome = RunToolUseCase(
            evidence=recorder,
            policy_evaluator=PermissionEngine(policy),
            sandbox=PathSandbox(self.project_root),
            tool_executor=ToolGateway(),
            finalize_permission=finalize_permission,
            evaluate_hooks=evaluate_pre_tool_hooks,
            request_approval=request_interactive_approval,
            create_recovery_checkpoint=create_backup_for_write,
            map_facts=map_tool_result,
            store_facts=write_facts,
        ).execute(
            intent,
            project_root=self.project_root,
            run_dir=run_dir,
            runtime_mode=self.runtime_mode,
            hooks=policy.hooks,
            facts_path=run_dir / "facts.jsonl",
        )
        recorder.append("run_completed", run_id=run_id, status="completed")
        return PythonRunResult(run_id=run_id, run_dir=run_dir, outcome=outcome)
