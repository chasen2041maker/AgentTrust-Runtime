"""Cross-process evidence append tests."""

from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder, read_verified_events
from agenttrust.adapters.evidence.run_lock import RunLock


def _append_events(run_dir_text: str, worker_id: int, count: int) -> None:
    run_dir = Path(run_dir_text)
    recorder = TraceRecorder(run_dir)
    for sequence in range(count):
        recorder.append(
            "worker_event",
            run_id=run_dir.name,
            worker_id=worker_id,
            sequence=sequence,
        )


def test_trace_recorder_serializes_cross_process_appends(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_lock"
    context = get_context("spawn")
    workers = [
        context.Process(target=_append_events, args=(str(run_dir), worker_id, 25))
        for worker_id in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert all(worker.exitcode == 0 for worker in workers)
    events = read_verified_events(run_dir)
    assert len(events) == 50
    assert {(int(event["worker_id"]), int(event["sequence"])) for event in events} == {
        (worker_id, sequence) for worker_id in range(2) for sequence in range(25)
    }


def test_trace_recorder_can_append_inside_a_run_level_operation_lock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_lock"
    operation_lock = RunLock(run_dir)

    with operation_lock:
        TraceRecorder(run_dir, run_lock=operation_lock).append("run_started", run_id="run_lock")

    assert read_verified_events(run_dir)[0]["event_type"] == "run_started"
