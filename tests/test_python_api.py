from __future__ import annotations

from pathlib import Path

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection


def test_python_sdk_executes_through_governed_pipeline(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("sdk\n", encoding="utf-8")

    result = AgentTrustRuntime(tmp_path, runtime_mode="test").execute("read_file", {"path": "README.md"})

    assert result.outcome.result is not None
    assert result.outcome.result.status == "ok"
    assert (result.run_dir / "trace.jsonl").exists()
    assert (result.run_dir / "policy-snapshot.yaml").exists()


def test_python_sdk_session_shares_run_identity_snapshot_and_evidence_chain(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("sdk\n", encoding="utf-8")
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice", agent_id="research-agent", session_id="session_123") as session:
        calls = [session.execute("read_file", {"path": "README.md"}) for _ in range(10)]
        assert session.session.status == "running"

    assert session.session.status == "completed"
    assert {call.outcome.intent.run_id for call in calls} == {session.run_id}
    assert [call.tool_call.tool_call_id for call in calls] == [f"call_{index:03d}" for index in range(1, 11)]
    assert {call.tool_call.arguments_digest for call in calls}
    events = read_trace(session.run_dir / "trace.jsonl")
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True
    assert all(event["run_id"] == session.run_id for event in events)
    assert all(event["session_id"] == "session_123" for event in events)
    assert all(event["actor_id"] == "alice" for event in events)
    assert all(event["agent_id"] == "research-agent" for event in events)
    assert {event["policy_version"] for event in events if "policy_version" in event} == {
        session.session.policy_version
    }
    projection = SQLiteStateProjection(tmp_path)
    assert projection.get_session(session.run_id)["status"] == "completed"
    assert [call["tool_call_id"] for call in projection.list_tool_calls(session.run_id)] == [
        f"call_{index:03d}" for index in range(1, 11)
    ]


def test_python_sdk_session_records_approval_lifecycle_before_execution(tmp_path: Path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice", session_id="session_approval") as session:
        result = session.execute("write_file", {"path": "summary.txt", "content": "approved"})

    assert result.outcome.result is not None
    assert (tmp_path / "summary.txt").read_text(encoding="utf-8") == "approved"
    events = read_trace(session.run_dir / "trace.jsonl")
    tool_statuses = [
        event["status"]
        for event in events
        if event["event_type"] in {"tool_call_requested", "tool_call_status_changed"}
    ]
    assert tool_statuses == ["requested", "waiting_approval", "approved", "executing", "succeeded"]
    session_statuses = [event["status"] for event in events if event["event_type"] == "session_status_changed"]
    assert session_statuses == ["running", "waiting_approval", "running", "completed"]
