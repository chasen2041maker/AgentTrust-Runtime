"""Tests for low-friction governed Python tool wrappers."""

from __future__ import annotations

import pytest

from agenttrust import AgentTrustRuntime, ApprovalPending, govern, governed_tool
from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.cli import main


def test_govern_runs_custom_tool_inside_an_existing_session(tmp_path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice") as session:
        add = govern(lambda left, right: left + right, session=session, tool_name="add_numbers", default_effect="allow")
        assert add(20, 22) == 42

    events = read_trace(session.run_dir / "trace.jsonl")
    intent = next(event for event in events if event["event_type"] == "tool_intent")
    assert intent["tool_name"] == "add_numbers"
    assert intent["source"] == "govern"
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True


def test_governed_tool_decorator_creates_a_governed_session_per_call(tmp_path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    @governed_tool(runtime=runtime, name="multiply", default_effect="allow")
    def multiply(left: int, right: int) -> int:
        return left * right

    assert multiply(6, 7) == 42


def test_govern_preserves_pending_approval_without_executing_the_callable(tmp_path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
    called = False

    def send_email(address: str) -> str:
        nonlocal called
        called = True
        return address

    with runtime.session(actor_id="alice") as session:
        guarded_send = govern(send_email, session=session, tool_name="send_email", default_effect="ask")
        with pytest.raises(ApprovalPending) as pending:
            guarded_send("alice@example.com")
        assert pending.value.session is session
        assert session.session.status == "waiting_approval"

    assert called is False
    assert session.session.status == "waiting_approval"


def test_governed_tool_can_be_reregistered_when_resuming_after_a_restart(tmp_path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
    called = False

    def send_email(address: str) -> str:
        nonlocal called
        called = True
        return address.upper()

    with runtime.session(actor_id="alice") as session:
        guarded_send = govern(send_email, session=session, tool_name="send_email", default_effect="ask")
        with pytest.raises(ApprovalPending) as pending:
            guarded_send("alice@example.com")

    assert main(
        [
            "--project-root",
            str(tmp_path),
            "approvals",
            "approve",
            pending.value.approval_id,
            "--reason",
            "reviewed",
        ]
    ) == 0
    with AgentTrustRuntime(tmp_path, runtime_mode="noninteractive").resume(
        session.run_id,
        resume_tools=[guarded_send],
    ) as resumed:
        outcome = resumed.resume_pending_approval()

    assert called is True
    assert outcome.outcome.result is not None
    assert outcome.outcome.result.output_preview == "'ALICE@EXAMPLE.COM'"
