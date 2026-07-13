"""Tests for governed session timeout behavior."""

from __future__ import annotations

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace


def test_timed_out_session_fails_before_tool_execution(tmp_path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice", timeout_seconds=0) as session:
        with pytest.raises(TimeoutError, match="timed out"):
            session.execute("read_file", {"path": "README.md"})

    assert session.session.status == "failed"
    events = read_trace(session.run_dir / "trace.jsonl")
    assert "session_timed_out" in [event["event_type"] for event in events]
    assert not any(event["event_type"] == "tool_intent" for event in events)
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True
