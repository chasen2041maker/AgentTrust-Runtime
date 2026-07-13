from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence import jsonl_store
from agenttrust.adapters.evidence.jsonl_store import (
    EVIDENCE_SCHEMA_VERSION,
    TraceRecorder,
    _event_hash,
    read_verified_events,
    verify_trace,
)
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection


def _rewrite_hash_chain(trace_path: Path, events: list[dict[str, object]]) -> None:
    previous_hash: str | None = None
    for event in events:
        event["previous_hash"] = previous_hash
        event["event_hash"] = _event_hash(event)
        previous_hash = event["event_hash"]
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def test_trace_head_avoids_repeated_full_trace_reads(tmp_path: Path, monkeypatch) -> None:
    recorder = TraceRecorder(tmp_path / "run")
    recorder.append("run_started", run_id="run")

    def fail_full_read(_path: Path):
        raise AssertionError("append should use trace-head.json instead of a full trace read")

    with monkeypatch.context() as nested:
        nested.setattr(jsonl_store, "read_trace", fail_full_read)
        for index in range(64):
            recorder.append("worker_event", run_id="run", sequence=index)

    assert (recorder.run_dir / "trace-head.json").exists()
    assert verify_trace(recorder.trace_path)["event_count"] == 65


def test_trace_recorder_owns_required_v1_envelope_fields(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path / "run")

    event = recorder.append("run_started")

    assert event["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert event["run_id"] == "run"
    assert event["event_sequence"] == 1
    with pytest.raises(ValueError, match="cannot override envelope"):
        recorder.append("invalid", schema_version="agenttrust.evidence/v2")


def test_stale_trace_head_falls_back_to_integrity_verification(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path / "run")
    recorder.append("run_started", run_id="run")
    recorder.append("run_completed", run_id="run")
    trace_path = recorder.trace_path
    trace_path.write_text(trace_path.read_text(encoding="utf-8").replace("run_started", "tampered", 1), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid evidence trace"):
        recorder.append("after_tamper", run_id="run")


def test_read_verified_events_migrates_legacy_evidence_to_v1_envelope(tmp_path: Path) -> None:
    run_dir = tmp_path / "legacy-run"
    run_dir.mkdir()
    legacy = {"event_type": "run_started", "run_id": "legacy-run", "created_at": "2026-07-13T00:00:00Z", "previous_hash": None}
    legacy["event_hash"] = _event_hash(legacy)
    (run_dir / "trace.jsonl").write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    event = read_verified_events(run_dir)[0]

    assert event["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert event["event_sequence"] == 1
    assert event["payload"]["run_id"] == "legacy-run"


def test_legacy_trace_head_is_rebuilt_before_first_v1_append(tmp_path: Path) -> None:
    run_dir = tmp_path / "legacy-run"
    run_dir.mkdir()
    legacy = {"event_type": "run_started", "run_id": "legacy-run", "created_at": "2026-07-13T00:00:00Z", "previous_hash": None}
    legacy["event_hash"] = _event_hash(legacy)
    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    stat = trace_path.stat()
    (run_dir / "trace-head.json").write_text(
        json.dumps(
            {
                "schema_version": "agenttrust.trace-head/v1",
                "event_count": 99,
                "head_hash": legacy["event_hash"],
                "trace_size": stat.st_size,
                "trace_mtime_ns": stat.st_mtime_ns,
            }
        ),
        encoding="utf-8",
    )

    appended = TraceRecorder(run_dir).append("worker_event")

    assert appended["event_sequence"] == 2
    assert [event["event_sequence"] for event in read_verified_events(run_dir)] == [1, 2]


def test_rebuild_run_rejects_unsupported_schema_without_changing_projection(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    recorder = TraceRecorder(run_dir)
    recorder.append(
        "session_created",
        session_id="session_123",
        actor_id="alice",
        status="created",
        updated_at="2026-07-13T00:00:00Z",
    )
    recorder.append("session_status_changed", status="running", updated_at="2026-07-13T00:00:01Z")
    projection = SQLiteStateProjection(tmp_path)
    projection.rebuild_run(run_dir)
    assert projection.get_session("run")["status"] == "running"

    trace_path = run_dir / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    events[0]["schema_version"] = "agenttrust.evidence/v2"
    _rewrite_hash_chain(trace_path, events)

    with pytest.raises(ValueError, match="unsupported evidence schema"):
        projection.rebuild_run(run_dir)

    assert projection.get_session("run")["status"] == "running"


def test_new_runtime_session_does_not_rebuild_every_run_projection(tmp_path: Path, monkeypatch) -> None:
    def fail_full_rebuild(self):
        raise AssertionError("new sessions must use incremental projection")

    monkeypatch.setattr(SQLiteStateProjection, "rebuild", fail_full_rebuild)
    (tmp_path / "README.md").write_text("incremental\n", encoding="utf-8")

    with AgentTrustRuntime(tmp_path, runtime_mode="test").session() as session:
        session.execute("read_file", {"path": "README.md"})

    assert SQLiteStateProjection(tmp_path).get_session(session.run_id)["status"] == "completed"
