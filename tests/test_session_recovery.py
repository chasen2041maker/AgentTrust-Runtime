"""End-to-end tests for resuming and cancelling persisted governed sessions."""

from __future__ import annotations

import json
from pathlib import Path

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
