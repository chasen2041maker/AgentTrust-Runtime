"""Tests for persisted, argument-bound approval requests and CLI decisions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection
from agenttrust.cli import main
from agenttrust.domain.approvals import ApprovalRequest


def test_approval_request_cannot_be_decided_twice() -> None:
    request = ApprovalRequest.create(
        run_id="run_123",
        tool_call_id="call_001",
        tool_name="write_file",
        arguments_digest="sha256:arguments",
        reason="write requires approval",
        requested_at="2026-07-13T00:00:00Z",
    )
    approved = request.approve("alice", "reviewed", "2026-07-13T00:00:01Z")

    assert approved.arguments_digest == "sha256:arguments"
    assert approved.decision == "approved"
    with pytest.raises(ValueError, match="already been decided"):
        approved.deny("alice", "changed mind")


def test_expired_approval_cannot_be_approved_or_denied_and_can_be_expired() -> None:
    request = ApprovalRequest.create(
        run_id="run_123",
        tool_call_id="call_001",
        tool_name="write_file",
        arguments_digest="sha256:arguments",
        reason="write requires approval",
        requested_at="2000-01-01T00:00:00Z",
        expires_at="2000-01-01T00:01:00Z",
    )

    assert request.is_expired("2000-01-01T00:01:00Z") is True
    with pytest.raises(ValueError, match="has expired"):
        request.approve("alice", "too late", "2000-01-01T00:02:00Z")
    with pytest.raises(ValueError, match="has expired"):
        request.deny("alice", "too late", "2000-01-01T00:02:00Z")

    expired = request.expire("agenttrust", "2000-01-01T00:02:00Z")
    assert expired.decision == "denied"
    assert expired.decision_reason == "approval_expired"


def test_persisted_approval_uses_trace_journal_sqlite_and_cli_decisions(tmp_path: Path, capsys) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")

    with runtime.session(actor_id="alice", session_id="session_approval") as session:
        pending = session.execute("write_file", {"path": "summary.txt", "content": "pending"})
        assert session.session.status == "waiting_approval"

    request = pending.approval_request
    assert request is not None
    assert pending.outcome.result is None
    assert not (tmp_path / "summary.txt").exists()
    assert session.session.status == "waiting_approval"
    journal_path = session.run_dir / "approvals.jsonl"
    journal = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert journal[0]["event_type"] == "approval_requested"
    assert journal[0]["arguments_digest"] == request.arguments_digest
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True

    assert main(["--project-root", str(tmp_path), "approvals", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["approval_id"] == request.approval_id
    assert listed[0]["decision"] == "pending"

    assert main(["--project-root", str(tmp_path), "approvals", "inspect", request.approval_id]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["arguments_digest"] == request.arguments_digest

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                request.approval_id,
                "--reason",
                "reviewed",
                "--approver",
                "reviewer",
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["decision"] == "approved"
    assert approved["arguments_digest"] == request.arguments_digest
    projection = SQLiteStateProjection(tmp_path)
    assert projection.get_approval(request.approval_id)["decision"] == "approved"
    journal = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert [entry["event_type"] for entry in journal] == ["approval_requested", "approval_decided"]
    events = read_trace(session.run_dir / "trace.jsonl")
    decision_event = next(event for event in events if event["event_type"] == "approval_decided")
    assert decision_event["arguments_digest"] == request.arguments_digest
    assert decision_event["approver_id"] == "reviewer"

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "deny",
                request.approval_id,
                "--reason",
                "too late",
            ]
        )
        == 2
    )
    assert "already been decided" in capsys.readouterr().err
