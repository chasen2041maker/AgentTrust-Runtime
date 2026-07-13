"""Unit tests for the framework-free governed session state machines."""

from __future__ import annotations

import pytest

from agenttrust.domain.lifecycle import LifecycleTransitionError
from agenttrust.domain.sessions import AgentSession, SessionToolCall, arguments_digest


def test_session_lifecycle_preserves_identity_and_policy_snapshot() -> None:
    session = AgentSession.create(
        run_id="run_123",
        actor_id="alice",
        agent_id="research-agent",
        session_id="session_123",
        policy_version="sha256:policy",
        created_at="2026-07-13T00:00:00Z",
    )

    completed = (
        session.start("2026-07-13T00:00:01Z")
        .wait_for_approval("2026-07-13T00:00:02Z")
        .resume("2026-07-13T00:00:03Z")
        .complete("2026-07-13T00:00:04Z")
    )

    assert completed.status == "completed"
    assert completed.is_terminal is True
    assert completed.run_id == "run_123"
    assert completed.actor_id == "alice"
    assert completed.agent_id == "research-agent"
    assert completed.policy_version == "sha256:policy"
    assert completed.updated_at == "2026-07-13T00:00:04Z"


def test_session_rejects_invalid_and_terminal_transitions() -> None:
    session = AgentSession.create(
        run_id="run_123",
        actor_id="alice",
        session_id="session_123",
        created_at="2026-07-13T00:00:00Z",
    )

    with pytest.raises(LifecycleTransitionError, match="created -> waiting_approval"):
        session.wait_for_approval()

    completed = session.start().complete()
    with pytest.raises(LifecycleTransitionError, match="completed -> running"):
        completed.resume()


def test_tool_call_lifecycle_binds_approval_to_canonical_arguments() -> None:
    first_digest = arguments_digest({"path": "README.md", "lines": [1, 2]})
    assert first_digest == arguments_digest({"lines": [1, 2], "path": "README.md"})
    assert first_digest != arguments_digest({"path": "secrets.env", "lines": [1, 2]})

    tool_call = SessionToolCall.create(
        run_id="run_123",
        session_id="session_123",
        sequence=2,
        tool_name="read_file",
        arguments={"path": "README.md", "lines": [1, 2]},
        policy_rule_id="tool:read-file",
        requested_at="2026-07-13T00:00:01Z",
    )
    succeeded = (
        tool_call.wait_for_approval("2026-07-13T00:00:02Z")
        .approve("2026-07-13T00:00:03Z")
        .start_execution("2026-07-13T00:00:04Z")
        .succeed("2026-07-13T00:00:05Z")
    )

    assert succeeded.tool_call_id == "call_002"
    assert succeeded.arguments_digest == first_digest
    assert succeeded.status == "succeeded"
    assert succeeded.is_terminal is True


def test_tool_call_rejects_invalid_transitions_and_invalid_sequences() -> None:
    with pytest.raises(ValueError, match="sequence"):
        SessionToolCall.create(
            run_id="run_123",
            session_id="session_123",
            sequence=0,
            tool_name="read_file",
            arguments={"path": "README.md"},
        )

    tool_call = SessionToolCall.create(
        run_id="run_123",
        session_id="session_123",
        sequence=1,
        tool_name="read_file",
        arguments={"path": "README.md"},
    )
    with pytest.raises(LifecycleTransitionError, match="requested -> succeeded"):
        tool_call.succeed()
