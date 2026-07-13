"""Python SDK entrypoint for framework-hosted agent loops."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Sequence
from uuid import uuid4

from agenttrust.adapters.evidence.approval_journal import JsonlApprovalJournal
from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.replay import replay_verified_run
from agenttrust.adapters.evidence.recovery import create_backup_for_write
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection
from agenttrust.adapters.policy.yaml_policy import load_policy, policy_digest, snapshot_policy
from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.adapters.tools.gateway import ToolGateway, ToolHandler
from agenttrust.adapters.verification.mapper import Fact, map_tool_result, write_facts
from agenttrust.application.governed_session import GovernedSession, SessionToolRun
from agenttrust.application.ports import EvidenceRecorderPort
from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.approvals import ApprovalRequest
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy
from agenttrust.domain.sessions import AgentSession, SessionToolCall
from agenttrust.groundguard_adapter import CoverageReport, verify_answer, write_coverage_report
from agenttrust.permissions import PermissionEngine, evaluate_pre_tool_hooks, finalize_permission, request_interactive_approval
from agenttrust.runtime.fixtures import create_run_id
from agenttrust.tools.registry import ToolSpec


@dataclass(frozen=True)
class PythonRunResult:
    run_id: str
    run_dir: Path
    outcome: ToolRunOutcome


@dataclass(frozen=True)
class FinalAnswerResult:
    """GroundGuard coverage plus the session completion decision for one answer."""

    coverage_report: CoverageReport
    completed: bool
    completion_action: str

    @property
    def status(self) -> str:
        return self.coverage_report.status


class AgentTrustSession:
    """Context-managed session that shares governance state across tool calls."""

    def __init__(
        self,
        governed_session: GovernedSession,
        evidence: ProjectingTraceRecorder,
        runtime_mode: str,
        restored: bool = False,
        pending_tool_call: SessionToolCall | None = None,
        pending_approval: ApprovalRequest | None = None,
        pending_arguments: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
        permission_engine: PermissionEngine | None = None,
        tool_gateway: ToolGateway | None = None,
    ) -> None:
        self._governed_session = governed_session
        self._evidence = evidence
        self._runtime_mode = runtime_mode
        self._restored = restored
        self._pending_tool_call = pending_tool_call
        self._pending_approval = pending_approval
        self._pending_arguments = pending_arguments
        self._deadline = monotonic() + timeout_seconds if timeout_seconds is not None else None
        self._permission_engine = permission_engine
        self._tool_gateway = tool_gateway
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
        if self._restored:
            self._entered = True
            return self
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
            if self._governed_session.session.status != "waiting_approval":
                self._governed_session.fail()
        elif self._has_timed_out():
            self._governed_session.timeout()
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
        self._raise_if_timed_out()
        return self._governed_session.execute(tool_name, arguments, source)

    def resume_pending_approval(self) -> SessionToolRun:
        if not self._entered:
            raise RuntimeError("session tools must execute inside the context manager")
        self._raise_if_timed_out()
        if self._pending_tool_call is None or self._pending_approval is None or self._pending_arguments is None:
            raise RuntimeError("session has no approved or denied pending tool call to resume")
        response = "approve" if self._pending_approval.decision == "approved" else "deny"
        result = self._governed_session.resume_tool_call(
            self._pending_tool_call,
            self._pending_arguments,
            response,
        )
        self._pending_tool_call = None
        self._pending_approval = None
        self._pending_arguments = None
        return result

    def finalize_answer(self, answer: str, required_fact_keys: Sequence[str] = ()) -> FinalAnswerResult:
        if not self._entered:
            raise RuntimeError("final answers must be submitted inside the context manager")
        self._raise_if_timed_out()
        facts = [fact for fact in self._governed_session.facts if isinstance(fact, Fact)]
        report = verify_answer(answer, facts, list(required_fact_keys))
        (self.run_dir / "final-answer.md").write_text(answer, encoding="utf-8")
        write_coverage_report(self.run_dir / "groundguard-report.json", report)
        outcome = self._governed_session.record_final_answer(answer, report.status, report.to_dict())
        return FinalAnswerResult(
            coverage_report=report,
            completed=outcome.completed,
            completion_action=outcome.completion_action,
        )

    def register_tool(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if self._permission_engine is None or self._tool_gateway is None:
            raise RuntimeError("session does not support dynamic tool registration")
        self._tool_gateway.register(spec.name, handler)
        self._permission_engine.register_tool_spec(spec)

    def _has_timed_out(self) -> bool:
        return self._deadline is not None and monotonic() >= self._deadline

    def _raise_if_timed_out(self) -> None:
        if self._has_timed_out():
            self._governed_session.timeout()
            raise TimeoutError("governed session timed out")


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
        timeout_seconds: float | None = None,
    ) -> AgentTrustSession:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or greater")
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
        tool_runner, permission_engine, tool_gateway = self._build_tool_runner(policy, evidence)
        governed_session = GovernedSession(
            session=AgentSession.create(
                run_id=run_id,
                actor_id=resolved_actor_id,
                agent_id=resolved_agent_id,
                session_id=resolved_session_id,
                policy_version=policy_version,
            ),
            tool_runner=tool_runner,
            evidence=evidence,
            project_root=self.project_root,
            run_dir=run_dir,
            runtime_mode=self.runtime_mode,
            hooks=policy.hooks,
            approval_journal=JsonlApprovalJournal(run_dir),
            defer_approvals=self.runtime_mode != "test",
            final_answer_mode=policy.final_answer_mode,
        )
        evidence.append("policy_snapshot", run_id=run_id, policy_version=policy_version, path=str(snapshot_path))
        return AgentTrustSession(
            governed_session,
            evidence,
            self.runtime_mode,
            timeout_seconds=timeout_seconds,
            permission_engine=permission_engine,
            tool_gateway=tool_gateway,
        )

    def resume(self, run_id: str, timeout_seconds: float | None = None) -> AgentTrustSession:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or greater")
        run_dir = self.project_root / ".agenttrust" / "runs" / run_id
        replayed = replay_verified_run(run_dir)
        session = replayed.session
        if session.status != "waiting_approval":
            raise ValueError(f"session {run_id} is not waiting for approval")
        waiting_calls = [call for call in replayed.tool_calls if call.status == "waiting_approval"]
        if len(waiting_calls) != 1:
            raise ValueError(f"session {run_id} must have exactly one waiting tool call to resume")
        tool_call = waiting_calls[0]
        approvals = [approval for approval in replayed.approvals if approval.tool_call_id == tool_call.tool_call_id]
        if len(approvals) != 1:
            raise ValueError(f"tool call {tool_call.tool_call_id} must have exactly one approval request")
        approval = approvals[0]
        if approval.is_pending:
            raise ValueError(f"approval {approval.approval_id} is still pending")
        policy_path = run_dir / "policy-snapshot.yaml"
        if not policy_path.exists():
            raise ValueError(f"policy snapshot not found for session {run_id}")
        if session.policy_version != policy_digest(policy_path.read_bytes()):
            raise ValueError(f"policy snapshot digest does not match verified session evidence for {run_id}")
        policy = load_policy(policy_path)
        recorder = TraceRecorder(run_dir)
        recorder.bind(
            actor_id=session.actor_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            policy_version=session.policy_version,
        )
        evidence = ProjectingTraceRecorder(recorder, SQLiteStateProjection(self.project_root))
        evidence.append(
            "run_resumed",
            run_id=run_id,
            tool_call_id=tool_call.tool_call_id,
            approval_id=approval.approval_id,
            approval_decision=approval.decision,
        )
        tool_runner, permission_engine, tool_gateway = self._build_tool_runner(policy, evidence)
        governed_session = GovernedSession(
            session=session,
            tool_runner=tool_runner,
            evidence=evidence,
            project_root=self.project_root,
            run_dir=run_dir,
            runtime_mode=self.runtime_mode,
            hooks=policy.hooks,
            approval_journal=JsonlApprovalJournal(run_dir),
            initial_sequence=max((call.sequence for call in replayed.tool_calls), default=0),
            started=True,
            initial_facts=replayed.facts,
            final_answer_mode=policy.final_answer_mode,
        )
        return AgentTrustSession(
            governed_session,
            evidence,
            self.runtime_mode,
            restored=True,
            pending_tool_call=tool_call,
            pending_approval=approval,
            pending_arguments=replayed.arguments_for(tool_call),
            timeout_seconds=timeout_seconds,
            permission_engine=permission_engine,
            tool_gateway=tool_gateway,
        )

    def cancel(self, run_id: str, actor_id: str | None = None) -> AgentSession:
        run_dir = self.project_root / ".agenttrust" / "runs" / run_id
        replayed = replay_verified_run(run_dir)
        session = replayed.session
        if session.is_terminal:
            raise ValueError(f"session {run_id} is already {session.status}")
        recorder = TraceRecorder(run_dir)
        recorder.bind(
            actor_id=actor_id or session.actor_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            policy_version=session.policy_version,
        )
        evidence = ProjectingTraceRecorder(recorder, SQLiteStateProjection(self.project_root))
        journal = JsonlApprovalJournal(run_dir)
        for approval in replayed.approvals:
            if approval.is_pending:
                decided = approval.deny(actor_id or session.actor_id, "session_cancelled")
                journal.append(evidence.append("approval_decided", **decided.to_dict()))
        for tool_call in replayed.tool_calls:
            if tool_call.status == "waiting_approval":
                denied = tool_call.deny_by_policy()
                evidence.append("tool_call_status_changed", **denied.to_dict())
        cancelled = session.cancel()
        evidence.append("session_status_changed", **cancelled.to_dict())
        evidence.append("run_completed", run_id=run_id, status=cancelled.status)
        return cancelled

    def _build_tool_runner(
        self, policy: Policy, evidence: EvidenceRecorderPort
    ) -> tuple[RunToolUseCase, PermissionEngine, ToolGateway]:
        permission_engine = PermissionEngine(policy)
        tool_gateway = ToolGateway()
        tool_runner = RunToolUseCase(
            evidence=evidence,
            policy_evaluator=permission_engine,
            sandbox=PathSandbox(self.project_root),
            tool_executor=tool_gateway,
            finalize_permission=finalize_permission,
            evaluate_hooks=evaluate_pre_tool_hooks,
            request_approval=request_interactive_approval,
            create_recovery_checkpoint=create_backup_for_write,
            map_facts=map_tool_result,
            store_facts=write_facts,
        )
        return tool_runner, permission_engine, tool_gateway

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
        tool_runner, _, _ = self._build_tool_runner(policy, recorder)
        outcome = tool_runner.execute(
            intent,
            project_root=self.project_root,
            run_dir=run_dir,
            runtime_mode=self.runtime_mode,
            hooks=policy.hooks,
            facts_path=run_dir / "facts.jsonl",
        )
        recorder.append("run_completed", run_id=run_id, status="completed")
        return PythonRunResult(run_id=run_id, run_dir=run_dir, outcome=outcome)
