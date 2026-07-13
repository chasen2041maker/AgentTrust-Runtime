"""Append-only JSONL evidence-store adapter."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any

from agenttrust.adapters.evidence.run_lock import RunLock
from agenttrust.domain.models import utc_now_iso


class TraceRecorder:
    """Persist evidence events to `.agenttrust/runs/{run_id}/trace.jsonl`."""

    def __init__(
        self,
        run_dir: Path,
        context: dict[str, Any] | None = None,
        run_lock: RunLock | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"
        self._context = dict(context or {})
        self._lock = RLock()
        self._run_lock = run_lock or RunLock(self.run_dir)

    def bind(self, **context: Any) -> None:
        """Attach run-scoped governance metadata to subsequent evidence events."""
        with self._lock:
            self._context.update({key: value for key, value in context.items() if value is not None})

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            with self._run_lock:
                events = read_trace(self.trace_path) if self.trace_path.exists() else []
                verification = verify_events(events)
                if verification["valid"] is not True:
                    raise ValueError(f"cannot append to invalid evidence trace: {verification.get('reason', 'unknown')}")
                event = {
                    "event_type": event_type,
                    "created_at": utc_now_iso(),
                    **self._context,
                    **payload,
                }
                event["previous_hash"] = verification["head_hash"]
                event["event_hash"] = _event_hash(event)
                with self.trace_path.open("a", encoding="utf-8", newline="\n") as trace_file:
                    trace_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
                    trace_file.write("\n")
                return event


def read_trace(trace_path: Path) -> list[dict[str, Any]]:
    """Read evidence events from a JSONL trace file."""
    if not trace_path.exists():
        raise FileNotFoundError(f"trace not found: {trace_path}")
    events: list[dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as trace_file:
        for line in trace_file:
            if line.strip():
                events.append(json.loads(line))
    return events


def verify_trace(trace_path: Path) -> dict[str, object]:
    """Verify the event hash chain independently of runtime execution."""

    return verify_events(read_trace(trace_path))


def verify_events(events: list[dict[str, Any]]) -> dict[str, object]:
    """Verify an already-read event sequence to avoid verification/read races."""

    previous_hash: str | None = None
    for index, event in enumerate(events, start=1):
        actual_hash = event.get("event_hash")
        if event.get("previous_hash") != previous_hash:
            return {"valid": False, "event_index": index, "reason": "previous_hash_mismatch"}
        if not isinstance(actual_hash, str) or _event_hash(event) != actual_hash:
            return {"valid": False, "event_index": index, "reason": "event_hash_mismatch"}
        previous_hash = actual_hash
    return {"valid": True, "event_count": len(events), "head_hash": previous_hash}


def read_verified_events(run_dir: Path) -> list[dict[str, Any]]:
    """Read one trace snapshot, verify it, and bind every event to its run directory."""

    events = read_trace(run_dir / "trace.jsonl")
    verification = verify_events(events)
    if verification["valid"] is not True:
        raise ValueError(f"invalid evidence trace: {verification.get('reason', 'unknown')}")
    for event in events:
        if event.get("run_id") != run_dir.name:
            raise ValueError("evidence event run_id does not match run directory")
    return events


def _event_hash(event: dict[str, Any]) -> str:
    canonical = {key: value for key, value in event.items() if key != "event_hash"}
    payload = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
