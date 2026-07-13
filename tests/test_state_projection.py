"""Tests for rebuilding SQLite state from verifiable JSONL evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder, _event_hash
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection, rebuild_state_from_traces
from agenttrust.cli import main


def _record_session_trace(project_root: Path, run_id: str = "run_session") -> None:
    recorder = TraceRecorder(project_root / ".agenttrust" / "runs" / run_id)
    recorder.append(
        "session_created",
        run_id=run_id,
        session_id="session_123",
        actor_id="alice",
        agent_id="research-agent",
        policy_version="sha256:policy",
        status="created",
        updated_at="2026-07-13T00:00:00Z",
    )
    recorder.append(
        "session_status_changed",
        run_id=run_id,
        status="running",
        updated_at="2026-07-13T00:00:01Z",
    )
    recorder.append(
        "tool_call_requested",
        run_id=run_id,
        session_id="session_123",
        tool_call_id="call_001",
        sequence=1,
        tool_name="write_file",
        arguments_digest="sha256:arguments",
        policy_rule_id="tool:write-file",
        status="requested",
        requested_at="2026-07-13T00:00:02Z",
        updated_at="2026-07-13T00:00:02Z",
    )
    recorder.append(
        "tool_call_status_changed",
        run_id=run_id,
        tool_call_id="call_001",
        status="waiting_approval",
        updated_at="2026-07-13T00:00:03Z",
    )
    recorder.append(
        "approval_requested",
        run_id=run_id,
        approval_id="approval_123",
        tool_call_id="call_001",
        tool_name="write_file",
        arguments_digest="sha256:arguments",
        policy_rule_id="tool:write-file",
        reason="write requires approval",
        requested_at="2026-07-13T00:00:03Z",
        expires_at="2026-07-13T01:00:00Z",
    )
    recorder.append(
        "approval_decided",
        run_id=run_id,
        approval_id="approval_123",
        arguments_digest="sha256:arguments",
        approver_id="alice",
        decision="approved",
        decision_reason="reviewed",
        decided_at="2026-07-13T00:00:04Z",
    )
    recorder.append(
        "tool_call_status_changed",
        run_id=run_id,
        tool_call_id="call_001",
        status="approved",
        updated_at="2026-07-13T00:00:04Z",
    )
    recorder.append(
        "tool_call_status_changed",
        run_id=run_id,
        tool_call_id="call_001",
        status="executing",
        updated_at="2026-07-13T00:00:05Z",
    )
    recorder.append(
        "tool_call_status_changed",
        run_id=run_id,
        tool_call_id="call_001",
        status="succeeded",
        updated_at="2026-07-13T00:00:06Z",
    )
    recorder.append(
        "session_status_changed",
        run_id=run_id,
        status="completed",
        updated_at="2026-07-13T00:00:07Z",
    )


def test_rebuild_projects_sessions_calls_and_approval_state(tmp_path: Path) -> None:
    _record_session_trace(tmp_path)

    result = rebuild_state_from_traces(tmp_path)
    projection = SQLiteStateProjection(tmp_path)

    assert result.traces_scanned == 1
    assert result.runs_projected == 1
    assert result.events_projected == 10
    assert projection.db_path.exists()
    assert projection.get_session("run_session") == {
        "run_id": "run_session",
        "session_id": "session_123",
        "actor_id": "alice",
        "agent_id": "research-agent",
        "policy_version": "sha256:policy",
        "status": "completed",
        "created_at": projection.get_session("run_session")["created_at"],
        "updated_at": "2026-07-13T00:00:07Z",
        "source_event_hash": projection.get_session("run_session")["source_event_hash"],
    }
    tool_call = projection.list_tool_calls("run_session")
    assert len(tool_call) == 1
    assert tool_call[0]["status"] == "succeeded"
    assert tool_call[0]["arguments_digest"] == "sha256:arguments"
    approvals = projection.list_approvals("run_session")
    assert len(approvals) == 1
    assert approvals[0]["decision"] == "approved"
    assert approvals[0]["arguments_digest"] == "sha256:arguments"


def test_rebuild_rejects_tampered_trace_without_erasing_existing_projection(tmp_path: Path) -> None:
    _record_session_trace(tmp_path)
    rebuild_state_from_traces(tmp_path)
    projection = SQLiteStateProjection(tmp_path)
    trace_path = tmp_path / ".agenttrust" / "runs" / "run_session" / "trace.jsonl"
    trace_path.write_text(trace_path.read_text(encoding="utf-8").replace("completed", "failed", 1), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid trace"):
        projection.rebuild()

    assert projection.get_session("run_session")["status"] == "completed"


def test_rebuild_rejects_a_valid_hash_chain_with_invalid_lifecycle(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path / ".agenttrust" / "runs" / "run_invalid_lifecycle")
    recorder.append(
        "session_created",
        run_id="run_invalid_lifecycle",
        session_id="session_123",
        actor_id="alice",
        status="created",
        updated_at="2026-07-13T00:00:00Z",
    )
    recorder.append(
        "session_status_changed",
        run_id="run_invalid_lifecycle",
        status="completed",
        updated_at="2026-07-13T00:00:01Z",
    )

    with pytest.raises(ValueError, match="created -> completed"):
        rebuild_state_from_traces(tmp_path)


def test_rebuild_run_rolls_back_when_lifecycle_projection_fails(tmp_path: Path) -> None:
    run_id = "run_atomic"
    _record_session_trace(tmp_path, run_id)
    run_dir = tmp_path / ".agenttrust" / "runs" / run_id
    projection = SQLiteStateProjection(tmp_path)
    projection.rebuild_run(run_dir)
    assert projection.get_session(run_id)["status"] == "completed"

    events = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    session_status = next(event for event in events if event["event_type"] == "session_status_changed")
    session_status["status"] = "completed"
    previous_hash = None
    for event in events:
        event["previous_hash"] = previous_hash
        event["event_hash"] = _event_hash(event)
        previous_hash = event["event_hash"]
    (run_dir / "trace.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="created -> completed"):
        projection.rebuild_run(run_dir)

    assert projection.get_session(run_id)["status"] == "completed"


def test_state_rebuild_cli_uses_the_jsonl_evidence_source(tmp_path: Path, capsys) -> None:
    _record_session_trace(tmp_path)

    assert main(["--project-root", str(tmp_path), "state", "rebuild"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"traces_scanned": 1, "runs_projected": 1, "events_projected": 10}


def test_projecting_recorder_does_not_hide_invalid_lifecycle_events(tmp_path: Path) -> None:
    class InvalidLifecycleProjection:
        rebuilt = False

        def apply_event(self, event: dict[str, object]) -> None:
            raise ValueError("invalid lifecycle")

        def rebuild(self) -> None:
            self.rebuilt = True

    projection = InvalidLifecycleProjection()
    recorder = ProjectingTraceRecorder(TraceRecorder(tmp_path / "run"), projection)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="invalid lifecycle"):
        recorder.append("session_status_changed", run_id="run", status="completed")

    assert projection.rebuilt is False
