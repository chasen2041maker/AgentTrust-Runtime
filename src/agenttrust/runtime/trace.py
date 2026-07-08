"""Append-only JSONL trace recording."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenttrust.schemas import utc_now_iso


class TraceRecorder:
    """Append trace events to `.agenttrust/runs/{run_id}/trace.jsonl`."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "event_type": event_type,
            "created_at": utc_now_iso(),
            **payload,
        }
        with self.trace_path.open("a", encoding="utf-8", newline="\n") as trace_file:
            trace_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            trace_file.write("\n")
        return event


def read_trace(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        raise FileNotFoundError(f"trace not found: {trace_path}")
    events: list[dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as trace_file:
        for line in trace_file:
            if line.strip():
                events.append(json.loads(line))
    return events
