"""Python SDK entrypoint for framework-hosted agent loops."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.recovery import create_backup_for_write
from agenttrust.adapters.evidence.approval_journal import JsonlApprovalJournal
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection
from agenttrust.adapters.policy.yaml_policy import load_policy, snapshot_policy
from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.adapters.tools.gateway import ToolGateway
from agenttrust.adapters.verification.mapper import map_tool_result, write_facts
from agenttrust.application.governed_session import GovernedSession, SessionToolRun
from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.sessions import AgentSession
from agenttrust.permissions import PermissionEngine, evaluate_pre_tool_hooks, finalize_permission, request_interactive_approval
from agenttrust.runtime.fixtures import create_run_id


@dataclass(frozen=True)
class PythonRunResult:
    run_id: str
    run_dir: Path
    outcome: ToolRunOutcome


class AgentTrustSession:
    """Context-managed session that shares governance state across tool calls."""

    def __init__(
        self,
        governed_session: GovernedSession,
        evidence: ProjectingTraceRecorder,
        runtime_mode: str,
    ) -> None:
        self._governed_session = governed_session
        self._evidence = evidence
        self._runtime_mode = runtime_mode
        self._entered = False

    @property
    def run_id(self) -> str:
        return self._governed_session.session.run_id

    @property
    def run_dir(self) -> Path:
        return self._governed_session.run_dir

    @property
    def session(self) -> AgentSession:
        return self._governed_session.session

    @property
    def facts(self) -> tuple[object, ...]:
        return self._governed_session.facts

    def __enter__(self) -> AgentTrustSession:
        if self._entered:
            raise RuntimeError("session context has already been entered")
        session = self._governed_session.session
        self._evidence.append(
            "run_started",
            run_id=session.run_id,
            source="python_sdk_session",
            runtime_mode=self._runtime_mode,
        )
        self._governed_session.start()
        self._entered = True
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        if exception is not None:
            self._governed_session.fail()
        else:
            self._governed_session.close()
        session = self._governed_session.session
        if session.is_terminal:
            self._evidence.append("run_completed", run_id=session.run_id, status=session.status)

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        source: str = "python_sdk",
    ) -> SessionToolRun:
        if not self._entered:
            raise RuntimeError("session tools must execute inside the context manager")
        return self._governed_session.execute(tool_name, arguments, source)


class AgentTrustRuntime:
    """Embed governed local tool execution inside a custom agent framework."""

    def __init__(self, project_root: Path, runtime_mode: str = "interactive") -> None:
        self.project_root = project_root.resolve()
        self.runtime_mode = runtime_mode

    def session(
        self,
        *,
        actor_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> AgentTrustSession:
        run_id = create_run_id()
        run_dir = self.project_root / ".agenttrust" / "runs" / run_id
        recorder = TraceRecorder(run_dir)
        policy_path = self.project_root / ".agenttrust" / "policy.yaml"
        policy = load_policy(policy_path)
        snapshot_path, policy_version = snapshot_policy(policy_path, run_dir)
        resolved_actor_id = actor_id or os.environ.get("AGENTTRUST_ACTOR_ID", "local-user")
        resolved_agent_id = agent_id if agent_id is not None else os.environ.get("AGENTTRUST_AGENT_ID")
        resolved_session_id = session_id or os.environ.get("AGENTTRUST_SESSION_ID") or f"session_{uuid4().hex}"
        recorder.bind(
            actor_id=resolved_actor_id,
            agent_id=resolved_agent_id,
            session_id=resolved_session_id,
            policy_version=policy_version,
        )
        evidence = ProjectingTraceRecorder(recorder, SQLiteStateProjection(self.project_root))
        governed_session = GovernedSession(
            session=AgentSession.create(
                run_id=run_id,
                actor_id=resolved_actor_id,
                agent_id=resolved_agent_id,
                session_id=resolved_session_id,
                policy_version=policy_version,
            ),
            tool_runner=RunToolUseCase(
                evidence=evidence,
                policy_evaluator=PermissionEngine(policy),
                sandbox=PathSandbox(self.project_root),
                tool_executor=ToolGateway(),
                finalize_permission=finalize_permission,
                evaluate_hooks=evaluate_pre_tool_hooks,
                request_approval=request_interactive_approval,
                create_recovery_checkpoint=create_backup_for_write,
                map_facts=map_tool_result,
                store_facts=write_facts,
            ),
            evidence=evidence,
            project_root=self.project_root,
            run_dir=run_dir,
            runtime_mode=self.runtime_mode,
            hooks=policy.hooks,
            approval_journal=JsonlApprovalJournal(run_dir),
            defer_approvals=self.runtime_mode != "test",
        )
        evidence.append("policy_snapshot", run_id=run_id, policy_version=policy_version, path=str(snapshot_path))
        return AgentTrustSession(governed_session, evidence, self.runtime_mode)

    def execute(self, tool_name: str, arguments: dict[str, object], source: str = "python_sdk") -> PythonRunResult:
        run_id = create_run_id()
        run_dir = self.project_root / ".agenttrust" / "runs" / run_id
        recorder = TraceRecorder(run_dir)
        policy_path = self.project_root / ".agenttrust" / "policy.yaml"
        policy = load_policy(policy_path)
        snapshot_path, policy_version = snapshot_policy(policy_path, run_dir)
        recorder.bind(
            actor_id=os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
            agent_id=os.environ.get("AGENTTRUST_AGENT_ID"),
            session_id=os.environ.get("AGENTTRUST_SESSION_ID"),
            policy_version=policy_version,
        )
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
