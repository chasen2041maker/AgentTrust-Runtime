"""Reconstruct authoritative run state from a verified evidence trace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.adapters.verification.mapper import Fact
from agenttrust.domain.approvals import ApprovalRequest
from agenttrust.domain.lifecycle import SessionStatus, ToolCallStatus
from agenttrust.domain.sessions import AgentSession, SessionToolCall, arguments_digest


@dataclass(frozen=True)
class ReplayedRunState:
    """Authoritative, lifecycle-validated state reconstructed from JSONL evidence."""

    session: AgentSession
    tool_calls: tuple[SessionToolCall, ...]
    approvals: tuple[ApprovalRequest, ...]
    facts: tuple[Fact, ...]
    arguments_by_tool_call: Mapping[str, dict[str, object]]

    def arguments_for(self, tool_call: SessionToolCall) -> dict[str, object]:
        try:
            return dict(self.arguments_by_tool_call[tool_call.tool_call_id])
        except KeyError as exc:
            raise ValueError(f"tool call {tool_call.tool_call_id} has no persisted tool intent") from exc


def replay_verified_run(run_dir: Path) -> ReplayedRunState:
    """Verify a run's hash chain, then rebuild its session state from its events."""

    run_dir = run_dir.resolve()
    trace_path = run_dir / "trace.jsonl"
    verification = verify_trace(trace_path)
    if verification["valid"] is not True:
        raise ValueError(f"invalid evidence trace: {verification.get('reason', 'unknown')}")
    return replay_events(read_trace(trace_path), expected_run_id=run_dir.name)


def replay_events(events: Sequence[Mapping[str, Any]], *, expected_run_id: str) -> ReplayedRunState:
    """Replay verified events while checking the lifecycle and evidence bindings."""

    session: AgentSession | None = None
    tool_calls: dict[str, SessionToolCall] = {}
    approvals: dict[str, ApprovalRequest] = {}
    arguments_by_tool_call: dict[str, dict[str, object]] = {}
    facts: list[Fact] = []

    for event in events:
        run_id = _required_text(event, "run_id")
        if run_id != expected_run_id:
            raise ValueError(f"evidence event run_id does not match run directory: {run_id}")
        event_type = _required_text(event, "event_type")

        if event_type == "session_created":
            if session is not None:
                raise ValueError(f"run {run_id} contains multiple session_created events")
            session = _session_from_event(event)
            continue

        if event_type == "session_status_changed":
            if session is None:
                raise ValueError("session status event precedes session creation")
            session = _apply_session_event(session, event)
            continue

        if event_type == "tool_call_requested":
            if session is None:
                raise ValueError("tool call request precedes session creation")
            tool_call = _tool_call_from_event(event)
            if tool_call.run_id != session.run_id or tool_call.session_id != session.session_id:
                raise ValueError("tool call request does not belong to the reconstructed session")
            if tool_call.tool_call_id in tool_calls:
                raise ValueError(f"run {run_id} contains duplicate tool call {tool_call.tool_call_id}")
            tool_calls[tool_call.tool_call_id] = tool_call
            continue

        if event_type == "tool_call_status_changed":
            tool_call_id = _required_text(event, "tool_call_id")
            current_tool_call = tool_calls.get(tool_call_id)
            if current_tool_call is None:
                raise ValueError(f"tool call status references an unknown call: {tool_call_id}")
            tool_calls[tool_call_id] = _apply_tool_call_event(current_tool_call, event)
            continue

        if event_type == "tool_intent":
            tool_call_id = _required_text(event, "tool_call_id")
            tool_name = _required_text(event, "tool_name")
            raw_arguments = event.get("arguments")
            if not isinstance(raw_arguments, Mapping) or not all(isinstance(key, str) for key in raw_arguments):
                raise ValueError(f"tool intent {tool_call_id} has invalid arguments")
            arguments = dict(cast(Mapping[str, object], raw_arguments))
            previous_arguments = arguments_by_tool_call.get(tool_call_id)
            if previous_arguments is not None and previous_arguments != arguments:
                raise ValueError(f"tool call {tool_call_id} has conflicting persisted arguments")
            arguments_by_tool_call[tool_call_id] = arguments
            requested_tool_call = tool_calls.get(tool_call_id)
            if requested_tool_call is not None and requested_tool_call.tool_name != tool_name:
                raise ValueError(f"tool intent {tool_call_id} does not match the requested tool name")
            continue

        if event_type == "approval_requested":
            approval = _approval_from_event(event)
            if approval.run_id != run_id or approval.approval_id in approvals:
                raise ValueError(f"run {run_id} contains an invalid approval request")
            approved_tool_call = tool_calls.get(approval.tool_call_id)
            if approved_tool_call is None or approved_tool_call.tool_name != approval.tool_name:
                raise ValueError(f"approval {approval.approval_id} does not match a requested tool call")
            if approved_tool_call.arguments_digest != approval.arguments_digest:
                raise ValueError(f"approval {approval.approval_id} does not match tool arguments")
            if any(item.tool_call_id == approval.tool_call_id for item in approvals.values()):
                raise ValueError(f"tool call {approval.tool_call_id} has multiple approval requests")
            approvals[approval.approval_id] = approval
            continue

        if event_type == "approval_decided":
            approval_id = _required_text(event, "approval_id")
            pending_approval = approvals.get(approval_id)
            if pending_approval is None:
                raise ValueError(f"approval decision references an unknown approval: {approval_id}")
            approvals[approval_id] = _apply_approval_event(pending_approval, event)
            continue

        if event_type == "fact_mapped":
            raw_facts = event.get("facts")
            if not isinstance(raw_facts, list):
                raise ValueError("fact_mapped event requires a facts list")
            facts.extend(_fact_from_event(raw_fact) for raw_fact in raw_facts)

    if session is None:
        raise ValueError(f"run {expected_run_id} has no session_created event")
    for tool_call_id, tool_call in tool_calls.items():
        recorded_arguments = arguments_by_tool_call.get(tool_call_id)
        if recorded_arguments is None:
            raise ValueError(f"tool call {tool_call_id} has no persisted tool intent")
        if arguments_digest(recorded_arguments) != tool_call.arguments_digest:
            raise ValueError(f"tool call {tool_call_id} arguments do not match its recorded digest")

    return ReplayedRunState(
        session=session,
        tool_calls=tuple(sorted(tool_calls.values(), key=lambda item: item.sequence)),
        approvals=tuple(approvals.values()),
        facts=tuple(facts),
        arguments_by_tool_call=arguments_by_tool_call,
    )


def _session_from_event(event: Mapping[str, Any]) -> AgentSession:
    status = cast(SessionStatus, _required_text(event, "status"))
    if status != "created":
        raise ValueError(f"session creation must have created status, received: {status}")
    return AgentSession(
        run_id=_required_text(event, "run_id"),
        actor_id=_required_text(event, "actor_id"),
        session_id=_required_text(event, "session_id"),
        created_at=_required_text(event, "created_at"),
        updated_at=_required_text(event, "updated_at"),
        agent_id=_optional_text(event, "agent_id"),
        policy_version=_optional_text(event, "policy_version"),
        status=status,
    )


def _apply_session_event(session: AgentSession, event: Mapping[str, Any]) -> AgentSession:
    _require_equal("session run_id", session.run_id, _required_text(event, "run_id"))
    _require_equal("session actor_id", session.actor_id, _required_text(event, "actor_id"))
    _require_equal("session session_id", session.session_id, _required_text(event, "session_id"))
    _require_equal("session agent_id", session.agent_id, _optional_text(event, "agent_id"))
    _require_equal("session policy_version", session.policy_version, _optional_text(event, "policy_version"))
    _require_equal("session created_at", session.created_at, _required_text(event, "created_at"))
    status = cast(SessionStatus, _required_text(event, "status"))
    updated_at = _required_text(event, "updated_at")
    return session.transition(status, updated_at)


def _tool_call_from_event(event: Mapping[str, Any]) -> SessionToolCall:
    sequence = event.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("tool call request requires an integer sequence")
    status = cast(ToolCallStatus, _required_text(event, "status"))
    if status != "requested":
        raise ValueError(f"tool call request must have requested status, received: {status}")
    return SessionToolCall(
        run_id=_required_text(event, "run_id"),
        session_id=_required_text(event, "session_id"),
        tool_call_id=_required_text(event, "tool_call_id"),
        sequence=sequence,
        tool_name=_required_text(event, "tool_name"),
        arguments_digest=_required_text(event, "arguments_digest"),
        requested_at=_required_text(event, "requested_at"),
        updated_at=_required_text(event, "updated_at"),
        policy_rule_id=_optional_text(event, "policy_rule_id"),
        status=status,
    )


def _apply_tool_call_event(tool_call: SessionToolCall, event: Mapping[str, Any]) -> SessionToolCall:
    _require_equal("tool call run_id", tool_call.run_id, _required_text(event, "run_id"))
    _require_equal("tool call session_id", tool_call.session_id, _required_text(event, "session_id"))
    _require_equal("tool call tool_name", tool_call.tool_name, _required_text(event, "tool_name"))
    _require_equal("tool call arguments_digest", tool_call.arguments_digest, _required_text(event, "arguments_digest"))
    _require_equal("tool call policy_rule_id", tool_call.policy_rule_id, _optional_text(event, "policy_rule_id"))
    _require_equal("tool call requested_at", tool_call.requested_at, _required_text(event, "requested_at"))
    sequence = event.get("sequence")
    if isinstance(sequence, bool) or sequence != tool_call.sequence:
        raise ValueError("tool call status event does not match the requested sequence")
    status = cast(ToolCallStatus, _required_text(event, "status"))
    return tool_call.transition(status, _required_text(event, "updated_at"))


def _approval_from_event(event: Mapping[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=_required_text(event, "approval_id"),
        run_id=_required_text(event, "run_id"),
        tool_call_id=_required_text(event, "tool_call_id"),
        tool_name=_required_text(event, "tool_name"),
        arguments_digest=_required_text(event, "arguments_digest"),
        policy_rule_id=_optional_text(event, "policy_rule_id"),
        reason=_required_text(event, "reason"),
        requested_at=_required_text(event, "requested_at"),
        expires_at=_optional_text(event, "expires_at"),
        decision="pending",
    )


def _apply_approval_event(approval: ApprovalRequest, event: Mapping[str, Any]) -> ApprovalRequest:
    _require_equal("approval run_id", approval.run_id, _required_text(event, "run_id"))
    _require_equal("approval tool_call_id", approval.tool_call_id, _required_text(event, "tool_call_id"))
    _require_equal("approval tool_name", approval.tool_name, _required_text(event, "tool_name"))
    _require_equal("approval arguments_digest", approval.arguments_digest, _required_text(event, "arguments_digest"))
    _require_equal("approval policy_rule_id", approval.policy_rule_id, _optional_text(event, "policy_rule_id"))
    _require_equal("approval reason", approval.reason, _required_text(event, "reason"))
    _require_equal("approval requested_at", approval.requested_at, _required_text(event, "requested_at"))
    _require_equal("approval expires_at", approval.expires_at, _optional_text(event, "expires_at"))
    decision = _required_text(event, "decision")
    approver_id = _required_text(event, "approver_id")
    decision_reason = _required_text(event, "decision_reason")
    decided_at = _required_text(event, "decided_at")
    if decision == "approved":
        return approval.approve(approver_id, decision_reason, decided_at)
    if decision == "denied":
        return approval.deny(approver_id, decision_reason, decided_at)
    raise ValueError(f"invalid approval decision: {decision}")


def _fact_from_event(raw: object) -> Fact:
    if not isinstance(raw, Mapping):
        raise ValueError("fact_mapped entries must be objects")
    unit = raw.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ValueError("fact unit must be a non-empty string or null")
    return Fact(
        key=_required_text(raw, "key"),
        value=_required_text(raw, "value"),
        unit=unit,
        source_tool_call_id=_required_text(raw, "source_tool_call_id"),
        source_tool_name=_required_text(raw, "source_tool_name"),
    )


def _required_text(event: Mapping[str, Any], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evidence event requires a non-empty string {key}")
    return value


def _optional_text(event: Mapping[str, Any], key: str) -> str | None:
    value = event.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evidence event requires {key} to be a non-empty string or null")
    return value


def _require_equal(label: str, expected: object, actual: object) -> None:
    if expected != actual:
        raise ValueError(f"{label} does not match its creation event")
