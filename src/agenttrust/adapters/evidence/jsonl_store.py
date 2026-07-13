"""Append-only JSONL evidence-store adapter."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any

from agenttrust.domain.models import utc_now_iso


class TraceRecorder:
    """Persist evidence events to `.agenttrust/runs/{run_id}/trace.jsonl`."""

    def __init__(self, run_dir: Path, context: dict[str, Any] | None = None) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"
        self._previous_hash = _last_event_hash(self.trace_path)
        self._context = dict(context or {})
        self._lock = RLock()

    def bind(self, **context: Any) -> None:
        """Attach run-scoped governance metadata to subsequent evidence events."""
        with self._lock:
            self._context.update({key: value for key, value in context.items() if value is not None})

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            event = {
                "event_type": event_type,
                "created_at": utc_now_iso(),
                **self._context,
                **payload,
            }
            event["previous_hash"] = self._previous_hash
            event["event_hash"] = _event_hash(event)
            with self.trace_path.open("a", encoding="utf-8", newline="\n") as trace_file:
                trace_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
                trace_file.write("\n")
            self._previous_hash = str(event["event_hash"])
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
    previous_hash: str | None = None
    for index, event in enumerate(read_trace(trace_path), start=1):
        actual_hash = event.get("event_hash")
        if event.get("previous_hash") != previous_hash:
            return {"valid": False, "event_index": index, "reason": "previous_hash_mismatch"}
        if not isinstance(actual_hash, str) or _event_hash(event) != actual_hash:
            return {"valid": False, "event_index": index, "reason": "event_hash_mismatch"}
        previous_hash = actual_hash
    return {"valid": True, "event_count": len(read_trace(trace_path)), "head_hash": previous_hash}


def _event_hash(event: dict[str, Any]) -> str:
    canonical = {key: value for key, value in event.items() if key != "event_hash"}
    payload = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _last_event_hash(trace_path: Path) -> str | None:
    if not trace_path.exists():
        return None
    events = read_trace(trace_path)
    if not events:
        return None
    value = events[-1].get("event_hash")
    return value if isinstance(value, str) else None
