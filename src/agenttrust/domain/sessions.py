"""Framework-free session and governed tool-call entities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Mapping

from agenttrust.domain.lifecycle import (
    SessionStatus,
    ToolCallStatus,
    assert_session_transition,
    assert_tool_call_transition,
    assert_valid_session_status,
    assert_valid_tool_call_status,
)
from agenttrust.domain.models import utc_now_iso


def arguments_digest(arguments: Mapping[str, object]) -> str:
    """Return a stable digest that binds an approval to exact tool arguments."""

    try:
        payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("tool arguments must be JSON serializable") from exc
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _require_text(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True)
class AgentSession:
    """One governed agent task, independent from any agent framework."""

    run_id: str
    actor_id: str
    session_id: str
    created_at: str
    updated_at: str
    agent_id: str | None = None
    policy_version: str | None = None
    status: SessionStatus = "created"

    def __post_init__(self) -> None:
        _require_text("run_id", self.run_id)
        _require_text("actor_id", self.actor_id)
        _require_text("session_id", self.session_id)
        _require_text("created_at", self.created_at)
        _require_text("updated_at", self.updated_at)
        if self.agent_id is not None:
            _require_text("agent_id", self.agent_id)
        if self.policy_version is not None:
            _require_text("policy_version", self.policy_version)
        assert_valid_session_status(self.status)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        actor_id: str,
        session_id: str,
        agent_id: str | None = None,
        policy_version: str | None = None,
        created_at: str | None = None,
    ) -> AgentSession:
        timestamp = created_at or utc_now_iso()
        return cls(
            run_id=run_id,
            actor_id=actor_id,
            session_id=session_id,
            agent_id=agent_id,
            policy_version=policy_version,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}

    def transition(self, status: SessionStatus, updated_at: str | None = None) -> AgentSession:
        assert_session_transition(self.status, status)
        return replace(self, status=status, updated_at=updated_at or utc_now_iso())

    def start(self, updated_at: str | None = None) -> AgentSession:
        return self.transition("running", updated_at)

    def wait_for_approval(self, updated_at: str | None = None) -> AgentSession:
        return self.transition("waiting_approval", updated_at)

    def resume(self, updated_at: str | None = None) -> AgentSession:
        return self.transition("running", updated_at)

    def complete(self, updated_at: str | None = None) -> AgentSession:
        return self.transition("completed", updated_at)

    def fail(self, updated_at: str | None = None) -> AgentSession:
        return self.transition("failed", updated_at)

    def cancel(self, updated_at: str | None = None) -> AgentSession:
        return self.transition("cancelled", updated_at)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "run_id": self.run_id,
            "actor_id": self.actor_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "policy_version": self.policy_version,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SessionToolCall:
    """A tool call belonging to one session, with approval-bound arguments."""

    run_id: str
    session_id: str
    tool_call_id: str
    sequence: int
    tool_name: str
    arguments_digest: str
    requested_at: str
    updated_at: str
    status: ToolCallStatus = "requested"
    policy_rule_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("run_id", self.run_id)
        _require_text("session_id", self.session_id)
        _require_text("tool_call_id", self.tool_call_id)
        _require_text("tool_name", self.tool_name)
        _require_text("arguments_digest", self.arguments_digest)
        _require_text("requested_at", self.requested_at)
        _require_text("updated_at", self.updated_at)
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        if self.policy_rule_id is not None:
            _require_text("policy_rule_id", self.policy_rule_id)
        assert_valid_tool_call_status(self.status)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        session_id: str,
        sequence: int,
        tool_name: str,
        arguments: Mapping[str, object],
        policy_rule_id: str | None = None,
        requested_at: str | None = None,
    ) -> SessionToolCall:
        timestamp = requested_at or utc_now_iso()
        return cls(
            run_id=run_id,
            session_id=session_id,
            tool_call_id=f"call_{sequence:03d}",
            sequence=sequence,
            tool_name=tool_name,
            arguments_digest=arguments_digest(arguments),
            policy_rule_id=policy_rule_id,
            requested_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {"policy_denied", "sandbox_denied", "succeeded", "failed"}

    def transition(self, status: ToolCallStatus, updated_at: str | None = None) -> SessionToolCall:
        assert_tool_call_transition(self.status, status)
        return replace(self, status=status, updated_at=updated_at or utc_now_iso())

    def wait_for_approval(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("waiting_approval", updated_at)

    def approve(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("approved", updated_at)

    def deny_by_policy(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("policy_denied", updated_at)

    def deny_by_sandbox(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("sandbox_denied", updated_at)

    def start_execution(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("executing", updated_at)

    def succeed(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("succeeded", updated_at)

    def fail(self, updated_at: str | None = None) -> SessionToolCall:
        return self.transition("failed", updated_at)

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "sequence": self.sequence,
            "tool_name": self.tool_name,
            "arguments_digest": self.arguments_digest,
            "policy_rule_id": self.policy_rule_id,
            "status": self.status,
            "requested_at": self.requested_at,
            "updated_at": self.updated_at,
        }
