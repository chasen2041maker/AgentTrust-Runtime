"""State-machine invariants for governed sessions and tool calls."""

from __future__ import annotations

from typing import Literal


SessionStatus = Literal["created", "running", "waiting_approval", "completed", "failed", "cancelled"]
ToolCallStatus = Literal[
    "requested",
    "policy_denied",
    "waiting_approval",
    "approved",
    "sandbox_denied",
    "executing",
    "succeeded",
    "failed",
]

SESSION_STATUSES: frozenset[SessionStatus] = frozenset(
    {"created", "running", "waiting_approval", "completed", "failed", "cancelled"}
)
TOOL_CALL_STATUSES: frozenset[ToolCallStatus] = frozenset(
    {
        "requested",
        "policy_denied",
        "waiting_approval",
        "approved",
        "sandbox_denied",
        "executing",
        "succeeded",
        "failed",
    }
)

_SESSION_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    "created": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting_approval", "completed", "failed", "cancelled"}),
    "waiting_approval": frozenset({"running", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

_TOOL_CALL_TRANSITIONS: dict[ToolCallStatus, frozenset[ToolCallStatus]] = {
    "requested": frozenset({"policy_denied", "waiting_approval", "sandbox_denied", "executing", "failed"}),
    "policy_denied": frozenset(),
    "waiting_approval": frozenset({"approved", "policy_denied", "failed"}),
    "approved": frozenset({"sandbox_denied", "executing", "failed"}),
    "sandbox_denied": frozenset(),
    "executing": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}


class LifecycleTransitionError(ValueError):
    """Raised when a session or tool call attempts an invalid state change."""


def assert_valid_session_status(status: str) -> None:
    if status not in SESSION_STATUSES:
        raise ValueError(f"unknown session status: {status}")


def assert_valid_tool_call_status(status: str) -> None:
    if status not in TOOL_CALL_STATUSES:
        raise ValueError(f"unknown tool call status: {status}")


def assert_session_transition(current: SessionStatus, target: SessionStatus) -> None:
    if target not in _SESSION_TRANSITIONS[current]:
        raise LifecycleTransitionError(f"invalid session transition: {current} -> {target}")


def assert_tool_call_transition(current: ToolCallStatus, target: ToolCallStatus) -> None:
    if target not in _TOOL_CALL_TRANSITIONS[current]:
        raise LifecycleTransitionError(f"invalid tool call transition: {current} -> {target}")


def is_terminal_session_status(status: SessionStatus) -> bool:
    return not _SESSION_TRANSITIONS[status]


def is_terminal_tool_call_status(status: ToolCallStatus) -> bool:
    return not _TOOL_CALL_TRANSITIONS[status]
