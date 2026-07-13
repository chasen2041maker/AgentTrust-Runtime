"""Application use case for a multi-call governed agent session."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agenttrust.application.ports import EvidenceRecord, EvidenceRecorderPort
from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.lifecycle import SessionStatus, ToolCallStatus
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import HookRule
from agenttrust.domain.sessions import AgentSession, SessionToolCall


@dataclass(frozen=True)
class SessionToolRun:
    """The governed result for one tool call inside an AgentSession."""

    session: AgentSession
    tool_call: SessionToolCall
    outcome: ToolRunOutcome


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
    ) -> None:
        self._session = session
        self._tool_runner = tool_runner
        self._evidence = evidence
        self._project_root = project_root
        self._run_dir = run_dir
        self._runtime_mode = runtime_mode
        self._hooks = hooks
        self._sequence = 0
        self._started = False
        self._active_tool_call: SessionToolCall | None = None
        self._facts: list[EvidenceRecord] = []

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
        return SessionToolRun(session=self._session, tool_call=completed_tool_call, outcome=outcome)

    def close(self) -> AgentSession:
        if not self._started:
            raise RuntimeError("session has not started")
        if self._session.status == "running":
            self._transition_session("completed")
        return self._session

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
