"""Python SDK entrypoint for framework-hosted agent loops."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Mapping, Sequence
from uuid import uuid4

from agenttrust.adapters.evidence.approval_journal import JsonlApprovalJournal
from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.replay import replay_verified_run
from agenttrust.adapters.evidence.recovery import bind_successful_write, create_backup_for_write
from agenttrust.adapters.evidence.run_lock import RunLock
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection
from agenttrust.adapters.policy.yaml_policy import load_policy, policy_digest, snapshot_policy
from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.adapters.tools.gateway import AsyncToolHandler, ToolGateway, ToolHandler
from agenttrust.adapters.verification.mapper import Fact, map_tool_result, write_facts
from agenttrust.application.governed_session import GovernedSession, SessionToolRun
from agenttrust.application.ports import EvidenceRecorderPort
from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.approvals import ApprovalRequest
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy
from agenttrust.domain.sessions import AgentSession, SessionToolCall
from agenttrust.groundguard_adapter import CoverageReport, verify_answer, write_coverage_report
from agenttrust.permissions import (
    PermissionEngine,
    approval_mode_for_runtime,
    evaluate_pre_tool_hooks,
    finalize_permission,
    request_interactive_approval,
)
from agenttrust.runtime.fixtures import create_run_id
from agenttrust.runtime.report import resolve_run_dir
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
        pending_tool_calls: Mapping[str, SessionToolCall] | None = None,
        pending_approvals: Mapping[str, ApprovalRequest] | None = None,
        pending_arguments_by_call: Mapping[str, Mapping[str, object]] | None = None,
        timeout_seconds: float | None = None,
        permission_engine: PermissionEngine | None = None,
        tool_gateway: ToolGateway | None = None,
        run_lock: RunLock | None = None,
        verification_mode: str = "fallback",
    ) -> None:
        self._governed_session = governed_session
        self._evidence = evidence
        self._runtime_mode = runtime_mode
        self._restored = restored
        self._pending_tool_call = pending_tool_call
        self._pending_approval = pending_approval
        self._pending_arguments = pending_arguments
        self._pending_tool_calls = dict(pending_tool_calls or {})
        self._pending_approvals = dict(pending_approvals or {})
        self._pending_arguments_by_call = {
            tool_call_id: dict(arguments)
            for tool_call_id, arguments in (pending_arguments_by_call or {}).items()
        }
        if pending_tool_call is not None and pending_approval is not None and pending_arguments is not None:
            self._pending_tool_calls.setdefault(pending_tool_call.tool_call_id, pending_tool_call)
            self._pending_approvals.setdefault(pending_tool_call.tool_call_id, pending_approval)
            self._pending_arguments_by_call.setdefault(pending_tool_call.tool_call_id, dict(pending_arguments))
        self._deadline = monotonic() + timeout_seconds if timeout_seconds is not None else None
        self._permission_engine = permission_engine
        self._tool_gateway = tool_gateway
        self._run_lock = run_lock
        self._verification_mode = verification_mode
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
        try:
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
        finally:
            if self._run_lock is not None:
                self._run_lock.release()
                self._run_lock = None

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

    @property
    def pending_approval_tool_call_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending_tool_calls))

    def resume_pending_approval(self, tool_call_id: str | None = None) -> SessionToolRun:
        if not self._entered:
            raise RuntimeError("session tools must execute inside the context manager")
        self._raise_if_timed_out()
        if tool_call_id is None:
            if len(self._pending_tool_calls) != 1:
                raise RuntimeError("session has multiple pending tool calls; specify tool_call_id")
            tool_call_id = next(iter(self._pending_tool_calls))
        tool_call = self._pending_tool_calls.get(tool_call_id)
        approval = self._pending_approvals.get(tool_call_id)
        arguments = self._pending_arguments_by_call.get(tool_call_id)
        if tool_call is None or approval is None or arguments is None:
            raise RuntimeError(f"session has no pending tool call to resume: {tool_call_id}")
        if approval.is_expired():
            raise RuntimeError(f"approval {approval.approval_id} has expired")
        if approval.is_pending:
            raise RuntimeError(f"approval {approval.approval_id} is still pending")
        response = "approve" if approval.decision == "approved" else "deny"
        result = self._governed_session.resume_tool_call(
            tool_call,
            arguments,
            response,
        )
        self._pending_tool_calls.pop(tool_call_id, None)
        self._pending_approvals.pop(tool_call_id, None)
        self._pending_arguments_by_call.pop(tool_call_id, None)
        self._pending_tool_call = None
        self._pending_approval = None
        self._pending_arguments = None
        return result

    def finalize_answer(self, answer: str, required_fact_keys: Sequence[str] = ()) -> FinalAnswerResult:
        if not self._entered:
            raise RuntimeError("final answers must be submitted inside the context manager")
        self._raise_if_timed_out()
        facts = [fact for fact in self._governed_session.facts if isinstance(fact, Fact)]
        report = verify_answer(
            answer,
            facts,
            list(required_fact_keys),
            allow_simulated_facts=self._runtime_mode == "test",
            verification_mode=self._verification_mode,
        )
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


class AgentTrustAsyncSession(AgentTrustSession):
    """Async context-managed session backed by the same policy and evidence semantics."""

    def __enter__(self) -> "AgentTrustAsyncSession":
        raise RuntimeError("use 'async with' for an async AgentTrust session")

    def __exit__(self, exception_type, exception, traceback) -> None:
        raise RuntimeError("use 'async with' for an async AgentTrust session")

    async def __aenter__(self) -> "AgentTrustAsyncSession":
        AgentTrustSession.__enter__(self)
        return self

    async def __aexit__(self, exception_type, exception, traceback) -> None:
        AgentTrustSession.__exit__(self, exception_type, exception, traceback)

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        source: str = "python_sdk",
    ) -> SessionToolRun:
        raise RuntimeError("use execute_async() with an async AgentTrust session")

    def resume_pending_approval(self, tool_call_id: str | None = None) -> SessionToolRun:
        raise RuntimeError("use resume_pending_approval_async() with an async AgentTrust session")

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, object],
        source: str = "python_sdk",
    ) -> SessionToolRun:
        if not self._entered:
            raise RuntimeError("session tools must execute inside the async context manager")
        self._raise_if_timed_out()
        return await self._governed_session.execute_async(tool_name, arguments, source)

    async def resume_pending_approval_async(self, tool_call_id: str | None = None) -> SessionToolRun:
        if not self._entered:
            raise RuntimeError("session tools must execute inside the async context manager")
        self._raise_if_timed_out()
        if tool_call_id is None:
            if len(self._pending_tool_calls) != 1:
                raise RuntimeError("session has multiple pending tool calls; specify tool_call_id")
            tool_call_id = next(iter(self._pending_tool_calls))
        tool_call = self._pending_tool_calls.get(tool_call_id)
        approval = self._pending_approvals.get(tool_call_id)
        arguments = self._pending_arguments_by_call.get(tool_call_id)
        if tool_call is None or approval is None or arguments is None:
            raise RuntimeError(f"session has no pending tool call to resume: {tool_call_id}")
        if approval.is_expired():
            raise RuntimeError(f"approval {approval.approval_id} has expired")
        if approval.is_pending:
            raise RuntimeError(f"approval {approval.approval_id} is still pending")
        response = "approve" if approval.decision == "approved" else "deny"
        result = await self._governed_session.resume_tool_call_async(tool_call, arguments, response)
        self._pending_tool_calls.pop(tool_call_id, None)
        self._pending_approvals.pop(tool_call_id, None)
        self._pending_arguments_by_call.pop(tool_call_id, None)
        return result

    def register_async_tool(self, spec: ToolSpec, handler: AsyncToolHandler) -> None:
        if self._permission_engine is None or self._tool_gateway is None:
            raise RuntimeError("session does not support dynamic tool registration")
        self._tool_gateway.register_async(spec.name, handler)
        self._permission_engine.register_tool_spec(spec)


class AgentTrustRuntime:
    """Embed governed local tool execution inside a custom agent framework."""

    def __init__(
        self,
        project_root: Path,
        runtime_mode: str = "interactive",
        approval_mode: str | None = None,
        allow_simulation: bool = False,
    ) -> None:
        self.project_root = project_root.resolve()
        self.runtime_mode = runtime_mode
        self.approval_mode = approval_mode_for_runtime(runtime_mode, approval_mode)
        self.allow_simulation = allow_simulation

    def session(
        self,
        *,
        actor_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        timeout_seconds: float | None = None,
        approval_ttl_seconds: int | None = None,
        approval_mode: str | None = None,
    ) -> AgentTrustSession:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or greater")
        if approval_ttl_seconds is not None and (
            isinstance(approval_ttl_seconds, bool)
            or not isinstance(approval_ttl_seconds, int)
            or approval_ttl_seconds <= 0
        ):
            raise ValueError("approval_ttl_seconds must be a positive integer")
        run_id = create_run_id()
        run_dir = resolve_run_dir(self.project_root, run_id)
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
        projection = SQLiteStateProjection(self.project_root)
        evidence = ProjectingTraceRecorder(recorder, projection)
        tool_runner, permission_engine, tool_gateway = self._build_tool_runner(policy, evidence)
        resolved_approval_mode = approval_mode_for_runtime(self.runtime_mode, approval_mode or self.approval_mode)
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
            approval_mode=resolved_approval_mode,
            simulation_allowed=self.allow_simulation,
            approval_journal=JsonlApprovalJournal(run_dir),
            approval_ttl_seconds=(
                approval_ttl_seconds if approval_ttl_seconds is not None else policy.approval_ttl_seconds
            ),
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
            verification_mode=policy.verification_mode,
        )

    def async_session(
        self,
        *,
        actor_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        timeout_seconds: float | None = None,
        approval_ttl_seconds: int | None = None,
        approval_mode: str | None = None,
    ) -> AgentTrustAsyncSession:
        """Create an async session with the same policy, approval, and evidence setup as session()."""

        prepared = self.session(
            actor_id=actor_id,
            agent_id=agent_id,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            approval_ttl_seconds=approval_ttl_seconds,
            approval_mode=approval_mode,
        )
        return self._as_async_session(prepared, timeout_seconds)

    @staticmethod
    def _as_async_session(
        prepared: AgentTrustSession, timeout_seconds: float | None
    ) -> AgentTrustAsyncSession:
        """Expose a prepared session through async-only mutation entry points."""

        return AgentTrustAsyncSession(
            prepared._governed_session,
            prepared._evidence,
            prepared._runtime_mode,
            restored=prepared._restored,
            pending_tool_call=prepared._pending_tool_call,
            pending_approval=prepared._pending_approval,
            pending_arguments=prepared._pending_arguments,
            pending_tool_calls=prepared._pending_tool_calls,
            pending_approvals=prepared._pending_approvals,
            pending_arguments_by_call=prepared._pending_arguments_by_call,
            timeout_seconds=timeout_seconds,
            permission_engine=prepared._permission_engine,
            tool_gateway=prepared._tool_gateway,
            run_lock=prepared._run_lock,
            verification_mode=prepared._verification_mode,
        )

    async def async_resume(
        self,
        run_id: str,
        timeout_seconds: float | None = None,
        tool_call_id: str | None = None,
        resume_tools: Sequence[object] = (),
    ) -> AgentTrustAsyncSession:
        """Asynchronously prepare one decided approval for native async execution."""

        self._validate_resume_tools(resume_tools)
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or greater")
        run_dir = resolve_run_dir(self.project_root, run_id)
        operation_lock = RunLock(run_dir)
        acquire_task = asyncio.create_task(asyncio.to_thread(operation_lock.acquire))
        try:
            await asyncio.shield(acquire_task)
        except asyncio.CancelledError:
            await acquire_task
            await asyncio.to_thread(operation_lock.release)
            raise

        prepare_task = asyncio.create_task(
            asyncio.to_thread(self._resume_locked, run_id, timeout_seconds, tool_call_id, (), operation_lock)
        )
        try:
            prepared = await asyncio.shield(prepare_task)
            restored = self._as_async_session(prepared, timeout_seconds)
            for resume_tool in resume_tools:
                register = getattr(resume_tool, "register")
                register(restored)
            return restored
        except asyncio.CancelledError:
            try:
                await prepare_task
            finally:
                await asyncio.to_thread(operation_lock.release)
            raise
        except BaseException:
            await asyncio.to_thread(operation_lock.release)
            raise

    def resume(
        self,
        run_id: str,
        timeout_seconds: float | None = None,
        tool_call_id: str | None = None,
        resume_tools: Sequence[object] = (),
    ) -> AgentTrustSession:
        """Resume a decided request while holding its run lock until the context exits."""

        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be zero or greater")
        run_dir = resolve_run_dir(self.project_root, run_id)
        operation_lock = RunLock(run_dir)
        operation_lock.acquire()
        try:
            return self._resume_locked(run_id, timeout_seconds, tool_call_id, resume_tools, operation_lock)
        except Exception:
            operation_lock.release()
            raise

    def _resume_locked(
        self,
        run_id: str,
        timeout_seconds: float | None,
        tool_call_id: str | None,
        resume_tools: Sequence[object],
        operation_lock: RunLock,
    ) -> AgentTrustSession:
        """Resume a decided request, optionally re-registering custom governed tools."""

        run_dir = resolve_run_dir(self.project_root, run_id)
        replayed = replay_verified_run(run_dir)
        session = replayed.session
        if session.status != "waiting_approval":
            raise ValueError(f"session {run_id} is not waiting for approval")
        waiting_calls = [call for call in replayed.tool_calls if call.status == "waiting_approval"]
        if not waiting_calls:
            raise ValueError(f"session {run_id} has no waiting tool calls to resume")
        waiting_by_id = {call.tool_call_id: call for call in waiting_calls}
        approvals_by_call: dict[str, ApprovalRequest] = {}
        for candidate_approval in replayed.approvals:
            if candidate_approval.tool_call_id not in waiting_by_id:
                continue
            if candidate_approval.tool_call_id in approvals_by_call:
                raise ValueError(f"tool call {candidate_approval.tool_call_id} has multiple approval requests")
            approvals_by_call[candidate_approval.tool_call_id] = candidate_approval
        if set(waiting_by_id) != set(approvals_by_call):
            missing = sorted(set(waiting_by_id) - set(approvals_by_call))
            raise ValueError(f"waiting tool calls have no approval request: {', '.join(missing)}")
        if tool_call_id is None:
            if len(waiting_by_id) == 1:
                tool_call_id = next(iter(waiting_by_id))
            else:
                resumable_ids = sorted(
                    call_id
                    for call_id, candidate_approval in approvals_by_call.items()
                    if not candidate_approval.is_pending and not candidate_approval.is_expired()
                )
                if len(resumable_ids) == 1:
                    tool_call_id = resumable_ids[0]
                else:
                    raise ValueError(f"session {run_id} has multiple pending tool calls; specify tool_call_id")
        tool_call = waiting_by_id.get(tool_call_id)
        approval = approvals_by_call.get(tool_call_id)
        if tool_call is None or approval is None:
            raise ValueError(f"session {run_id} has no waiting tool call: {tool_call_id}")
        if approval.is_expired():
            raise ValueError(f"approval {approval.approval_id} has expired")
        if approval.is_pending:
            raise ValueError(f"approval {approval.approval_id} is still pending")
        policy_path = run_dir / "policy-snapshot.yaml"
        if not policy_path.exists():
            raise ValueError(f"policy snapshot not found for session {run_id}")
        if session.policy_version != policy_digest(policy_path.read_bytes()):
            raise ValueError(f"policy snapshot digest does not match verified session evidence for {run_id}")
        policy = load_policy(policy_path)
        self._validate_resume_tools(resume_tools)
        recorder = TraceRecorder(run_dir, run_lock=operation_lock)
        recorder.bind(
            actor_id=session.actor_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            policy_version=session.policy_version,
        )
        projection = SQLiteStateProjection(self.project_root)
        projection.rebuild_run(run_dir)
        evidence = ProjectingTraceRecorder(recorder, projection)
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
            approval_mode=self.approval_mode,
            simulation_allowed=self.allow_simulation,
            approval_journal=JsonlApprovalJournal(run_dir),
            approval_ttl_seconds=policy.approval_ttl_seconds,
            initial_sequence=max((call.sequence for call in replayed.tool_calls), default=0),
            pending_tool_call_ids=tuple(waiting_by_id),
            started=True,
            initial_facts=replayed.facts,
            final_answer_mode=policy.final_answer_mode,
        )
        restored_session = AgentTrustSession(
            governed_session,
            evidence,
            self.runtime_mode,
            restored=True,
            pending_tool_call=tool_call,
            pending_approval=approval,
            pending_arguments=replayed.arguments_for(tool_call),
            pending_tool_calls=waiting_by_id,
            pending_approvals=approvals_by_call,
            pending_arguments_by_call={
                call_id: replayed.arguments_for(call) for call_id, call in waiting_by_id.items()
            },
            timeout_seconds=timeout_seconds,
            permission_engine=permission_engine,
            tool_gateway=tool_gateway,
            run_lock=operation_lock,
            verification_mode=policy.verification_mode,
        )
        for resume_tool in resume_tools:
            register = getattr(resume_tool, "register", None)
            assert callable(register)
            register(restored_session)
        return restored_session

    @staticmethod
    def _validate_resume_tools(resume_tools: Sequence[object]) -> None:
        for resume_tool in resume_tools:
            if not callable(getattr(resume_tool, "register", None)):
                raise ValueError("resume tools must provide a callable register(session) attribute")

    def cancel(self, run_id: str, actor_id: str | None = None) -> AgentSession:
        run_dir = resolve_run_dir(self.project_root, run_id)
        with RunLock(run_dir) as operation_lock:
            return self._cancel_locked(run_id, actor_id, operation_lock)

    def _cancel_locked(self, run_id: str, actor_id: str | None, operation_lock: RunLock) -> AgentSession:
        run_dir = resolve_run_dir(self.project_root, run_id)
        replayed = replay_verified_run(run_dir)
        session = replayed.session
        if session.is_terminal:
            raise ValueError(f"session {run_id} is already {session.status}")
        recorder = TraceRecorder(run_dir, run_lock=operation_lock)
        recorder.bind(
            actor_id=actor_id or session.actor_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            policy_version=session.policy_version,
        )
        projection = SQLiteStateProjection(self.project_root)
        projection.rebuild_run(run_dir)
        evidence = ProjectingTraceRecorder(recorder, projection)
        journal = JsonlApprovalJournal(run_dir)
        for approval in replayed.approvals:
            if approval.is_pending:
                expired = approval.is_expired()
                decided = (
                    approval.expire(actor_id or session.actor_id)
                    if expired
                    else approval.deny(actor_id or session.actor_id, "session_cancelled")
                )
                if expired:
                    evidence.append(
                        "approval_expired",
                        run_id=approval.run_id,
                        tool_call_id=approval.tool_call_id,
                        approval_id=approval.approval_id,
                        expires_at=approval.expires_at,
                    )
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
            bind_recovery_checkpoint=bind_successful_write,
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
            simulation_allowed=self.allow_simulation,
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
            approval_mode=self.approval_mode,
            hooks=policy.hooks,
            facts_path=run_dir / "facts.jsonl",
        )
        recorder.append("run_completed", run_id=run_id, status="completed")
        return PythonRunResult(run_id=run_id, run_dir=run_dir, outcome=outcome)

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, object],
        source: str = "python_sdk",
    ) -> PythonRunResult:
        """Execute one governed tool call through the async session API."""

        async with self.async_session() as session:
            tool_run = await session.execute_async(tool_name, arguments, source)
        return PythonRunResult(run_id=session.run_id, run_dir=session.run_dir, outcome=tool_run.outcome)
