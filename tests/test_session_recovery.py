"""End-to-end tests for resuming and cancelling persisted governed sessions."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.jsonl_store import verify_trace
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection, rebuild_state_from_traces
from agenttrust.cli import main


def _create_waiting_write_session(project_root: Path, filename: str):
    runtime = AgentTrustRuntime(project_root, runtime_mode="noninteractive")
    with runtime.session(actor_id="alice", session_id=f"session_{filename}") as session:
        pending = session.execute("write_file", {"path": filename, "content": "resumed content"})
    assert pending.approval_request is not None
    assert session.session.status == "waiting_approval"
    return session, pending.approval_request


def test_cli_resume_rehydrates_waiting_session_after_approval(tmp_path: Path, capsys) -> None:
    session, approval = _create_waiting_write_session(tmp_path, "resumed.txt")

    assert main(["--project-root", str(tmp_path), "run", "resume", session.run_id]) == 2
    assert "still pending" in capsys.readouterr().err

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                approval.approval_id,
                "--reason",
                "reviewed",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["--project-root", str(tmp_path), "run", "resume", session.run_id]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["session_status"] == "completed"
    assert output["tool_call_status"] == "succeeded"
    assert (tmp_path / "resumed.txt").read_text(encoding="utf-8") == "resumed content"
    projection = SQLiteStateProjection(tmp_path)
    assert projection.get_session(session.run_id)["status"] == "completed"
    assert projection.list_tool_calls(session.run_id)[0]["status"] == "succeeded"
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True
    assert rebuild_state_from_traces(tmp_path).events_projected >= 10


def test_cli_cancel_denies_pending_approval_and_prevents_execution(tmp_path: Path, capsys) -> None:
    session, approval = _create_waiting_write_session(tmp_path, "cancelled.txt")

    assert main(["--project-root", str(tmp_path), "run", "cancel", session.run_id]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "cancelled"
    assert not (tmp_path / "cancelled.txt").exists()
    projection = SQLiteStateProjection(tmp_path)
    assert projection.get_session(session.run_id)["status"] == "cancelled"
    assert projection.get_approval(approval.approval_id)["decision"] == "denied"
    assert projection.list_tool_calls(session.run_id)[0]["status"] == "policy_denied"
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True


def test_resume_and_approval_decision_do_not_trust_tampered_sqlite_state(tmp_path: Path, capsys) -> None:
    session, approval = _create_waiting_write_session(tmp_path, "cache-tamper.txt")

    state_path = tmp_path / ".agenttrust" / "state.db"
    with sqlite3.connect(state_path) as connection:
        connection.execute(
            """
            UPDATE approvals
            SET decision = 'approved', approver_id = 'attacker', decision_reason = 'tampered', decided_at = '2026-07-13T00:00:00Z'
            WHERE approval_id = ?
            """,
            (approval.approval_id,),
        )

    assert main(["--project-root", str(tmp_path), "run", "resume", session.run_id]) == 2
    assert "still pending" in capsys.readouterr().err
    assert not (tmp_path / "cache-tamper.txt").exists()

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                approval.approval_id,
                "--reason",
                "reviewed verified evidence",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--project-root", str(tmp_path), "run", "resume", session.run_id]) == 0
    assert (tmp_path / "cache-tamper.txt").read_text(encoding="utf-8") == "resumed content"


def test_resume_rejects_policy_snapshot_digest_mismatch(tmp_path: Path, capsys) -> None:
    session, approval = _create_waiting_write_session(tmp_path, "policy-tamper.txt")

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                approval.approval_id,
                "--reason",
                "reviewed",
            ]
        )
        == 0
    )
    capsys.readouterr()
    (session.run_dir / "policy-snapshot.yaml").write_text("rules: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="policy snapshot digest"):
        AgentTrustRuntime(tmp_path, runtime_mode="noninteractive").resume(session.run_id)


def test_resume_rebuilds_facts_from_verified_trace_not_mutable_ledger(tmp_path: Path, capsys) -> None:
    (tmp_path / "README.md").write_text("verified facts\n", encoding="utf-8")
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
    with runtime.session(actor_id="alice", session_id="session_facts") as session:
        session.execute("read_file", {"path": "README.md"})
        pending = session.execute("write_file", {"path": "facts-resumed.txt", "content": "resumed"})

    assert pending.approval_request is not None
    (session.run_dir / "facts.jsonl").write_text("not valid json\n", encoding="utf-8")
    approval = pending.approval_request
    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                approval.approval_id,
                "--reason",
                "reviewed",
            ]
        )
        == 0
    )
    capsys.readouterr()

    with runtime.resume(session.run_id) as resumed:
        assert any(getattr(fact, "key", "") == "read_file_bytes" for fact in resumed.facts)
        resumed.resume_pending_approval()

    assert (tmp_path / "facts-resumed.txt").read_text(encoding="utf-8") == "resumed"
