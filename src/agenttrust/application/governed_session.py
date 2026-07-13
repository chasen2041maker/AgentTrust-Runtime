"""Application use case for a multi-call governed agent session."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from agenttrust.application.ports import ApprovalJournalPort, EvidenceRecord, EvidenceRecorderPort
from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.lifecycle import SessionStatus, ToolCallStatus
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import HookRule
from agenttrust.domain.approvals import ApprovalRequest
from agenttrust.domain.sessions import AgentSession, SessionToolCall, arguments_digest


@dataclass(frozen=True)
class SessionToolRun:
    """The governed result for one tool call inside an AgentSession."""

    session: AgentSession
    tool_call: SessionToolCall
    outcome: ToolRunOutcome
    approval_request: ApprovalRequest | None = None


@dataclass(frozen=True)
class FinalAnswerOutcome:
    """The completion decision after recording one GroundGuard answer check."""

    completed: bool
    completion_action: str


class GovernedSession:
    """Keep a single run, policy snapshot, identity, and evidence chain across calls."""

    def __init__(
        self,
        *,
        session: AgentSession,
        tool_runner: RunToolUseCase,
        evidence: EvidenceRecorderPort,
        project_root: Path,
        run_dir: Path,
        runtime_mode: str,
        hooks: tuple[HookRule, ...],
        approval_journal: ApprovalJournalPort | None = None,
        defer_approvals: bool = False,
        initial_sequence: int = 0,
        started: bool = False,
        initial_facts: Sequence[EvidenceRecord] = (),
        final_answer_mode: str = "warn",
    ) -> None:
        self._session = session
        self._tool_runner = tool_runner
        self._evidence = evidence
        self._project_root = project_root
        self._run_dir = run_dir
        self._runtime_mode = runtime_mode
        self._hooks = hooks
        self._approval_journal = approval_journal
        self._defer_approvals = defer_approvals
        self._sequence = initial_sequence
        self._started = started
        self._active_tool_call: SessionToolCall | None = None
        self._facts: list[EvidenceRecord] = list(initial_facts)
        self._final_answer_mode = final_answer_mode
        self._completion_blocked = False

    @property
    def session(self) -> AgentSession:
        return self._session

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def facts(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._facts)

    def start(self) -> AgentSession:
        if self._started:
            raise RuntimeError("session has already started")
        self._evidence.append("session_created", **self._session.to_dict())
        self._started = True
        self._transition_session("running")
        return self._session

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        source: str = "python_sdk",
    ) -> SessionToolRun:
        if not self._started:
            raise RuntimeError("session must be started before executing tools")
        if self._session.status != "running":
            raise RuntimeError(f"cannot execute tools while session is {self._session.status}")

        self._sequence += 1
        tool_call = SessionToolCall.create(
            run_id=self._session.run_id,
            session_id=self._session.session_id,
            sequence=self._sequence,
            tool_name=tool_name,
            arguments=arguments,
        )
        self._active_tool_call = tool_call
        self._evidence.append("tool_call_requested", **tool_call.to_dict())
        intent = ToolIntent(
            run_id=self._session.run_id,
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            source=source,
            runtime_mode=self._runtime_mode,
        )
        try:
            outcome = self._tool_runner.execute(
                intent,
                project_root=self._project_root,
                run_dir=self._run_dir,
                runtime_mode=self._runtime_mode,
                hooks=self._hooks,
                facts_path=self._run_dir / "facts.jsonl",
                on_tool_call_status=self._record_tool_status,
                defer_approval=self._defer_approvals,
            )
        except Exception:
            if not self._session.is_terminal:
                self._transition_session("failed")
            raise
        finally:
            completed_tool_call = self._active_tool_call
            self._active_tool_call = None

        if completed_tool_call is None:
            raise RuntimeError("tool call lifecycle did not complete")
        self._facts.extend(outcome.facts)
        approval_request = None
        if outcome.final_permission.final_effect == "ask":
            approval_request = ApprovalRequest.create(
                run_id=self._session.run_id,
                tool_call_id=completed_tool_call.tool_call_id,
                tool_name=completed_tool_call.tool_name,
                arguments_digest=completed_tool_call.arguments_digest,
                policy_rule_id=outcome.permission_decision.rule_id,
                reason=outcome.permission_decision.reason,
            )
            approval_event = self._evidence.append("approval_requested", **approval_request.to_dict())
            if self._approval_journal is not None:
                self._approval_journal.append(approval_event)
        return SessionToolRun(
            session=self._session,
            tool_call=completed_tool_call,
            outcome=outcome,
            approval_request=approval_request,
        )

    def close(self) -> AgentSession:
        if not self._started:
            raise RuntimeError("session has not started")
        if self._session.status == "running" and not self._completion_blocked:
            self._transition_session("completed")
        return self._session

    def record_final_answer(
        self,
        answer: str,
        coverage_status: str,
        coverage_payload: Mapping[str, object],
    ) -> FinalAnswerOutcome:
        if not self._started:
            raise RuntimeError("session has not started")
        if self._session.status != "running":
            raise RuntimeError(f"cannot finalize an answer while session is {self._session.status}")
        self._evidence.append("final_answer_submitted", run_id=self._session.run_id, answer=answer)
        self._evidence.append("groundguard_check", run_id=self._session.run_id, **coverage_payload)
        if coverage_status == "verified":
            self._completion_blocked = False
            self._transition_session("completed")
            return FinalAnswerOutcome(completed=True, completion_action="completed")
        if self._final_answer_mode == "warn":
            self._completion_blocked = False
            self._transition_session("completed")
            return FinalAnswerOutcome(completed=True, completion_action="warned")
        self._completion_blocked = True
        if self._final_answer_mode == "require_revision":
            return FinalAnswerOutcome(completed=False, completion_action="revision_required")
        return FinalAnswerOutcome(completed=False, completion_action="completion_denied")

    def resume_tool_call(
        self,
        tool_call: SessionToolCall,
        arguments: Mapping[str, object],
        approval_response: str,
        source: str = "approval_resume",
    ) -> SessionToolRun:
        if not self._started:
            raise RuntimeError("session has not been restored")
        if self._session.status != "waiting_approval":
            raise RuntimeError(f"cannot resume a tool while session is {self._session.status}")
        if tool_call.status != "waiting_approval":
            raise RuntimeError(f"cannot resume tool call while it is {tool_call.status}")
        if approval_response not in {"approve", "deny"}:
            raise ValueError(f"invalid persisted approval response: {approval_response}")
        if arguments_digest(arguments) != tool_call.arguments_digest:
            raise ValueError("persisted tool arguments do not match the approval-bound digest")

        self._active_tool_call = tool_call
        intent = ToolIntent(
            run_id=self._session.run_id,
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            arguments=dict(arguments),
            source=source,
            runtime_mode=self._runtime_mode,
        )
        try:
            outcome = self._tool_runner.execute(
                intent,
                project_root=self._project_root,
                run_dir=self._run_dir,
                runtime_mode=self._runtime_mode,
                hooks=self._hooks,
                facts_path=self._run_dir / "facts.jsonl",
                on_tool_call_status=self._record_tool_status,
                approval_response=approval_response,
            )
        except Exception:
            if not self._session.is_terminal:
                self._transition_session("failed")
            raise
        finally:
            completed_tool_call = self._active_tool_call
            self._active_tool_call = None

        if completed_tool_call is None:
            raise RuntimeError("resumed tool call lifecycle did not complete")
        self._facts.extend(outcome.facts)
        return SessionToolRun(session=self._session, tool_call=completed_tool_call, outcome=outcome)

    def fail(self) -> AgentSession:
        if self._started and not self._session.is_terminal:
            self._transition_session("failed")
        return self._session

    def _record_tool_status(self, status: ToolCallStatus) -> None:
        if self._active_tool_call is None:
            raise RuntimeError("tool call lifecycle event has no active tool call")
        if status == "waiting_approval":
            self._transition_session("waiting_approval")
        elif self._session.status == "waiting_approval":
            self._transition_session("running")
        self._active_tool_call = self._active_tool_call.transition(status)
        self._evidence.append("tool_call_status_changed", **self._active_tool_call.to_dict())

    def _transition_session(self, status: SessionStatus) -> None:
        self._session = self._session.transition(status)
        self._evidence.append("session_status_changed", **self._session.to_dict())
        if status == "completed":
            self._evidence.append("session_completed", run_id=self._session.run_id)
