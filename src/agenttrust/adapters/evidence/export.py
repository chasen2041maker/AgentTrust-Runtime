"""Portable NDJSON evidence export adapter for SIEM/telemetry ingestion."""

from __future__ import annotations

import json
from pathlib import Path

from agenttrust.adapters.evidence.jsonl_store import read_trace


def export_ndjson(run_dir: Path) -> Path:
    """Export verified-shape evidence events to a stable NDJSON artifact."""
    trace_path = run_dir / "trace.jsonl"
    target = run_dir / "evidence-export.ndjson"
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for event in read_trace(trace_path):
            payload = {"resource": "agenttrust.runtime", "event": event}
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    return target
