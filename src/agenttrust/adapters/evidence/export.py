"""Portable NDJSON evidence export adapter for SIEM/telemetry ingestion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from agenttrust.adapters.evidence.jsonl_store import read_verified_events


def export_ndjson(run_dir: Path) -> Path:
    """Export verified-shape evidence events to a stable NDJSON artifact."""
    target = run_dir / "evidence-export.ndjson"
    events = read_verified_events(run_dir)
    with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=run_dir, delete=False) as handle:
        temporary_path = Path(handle.name)
        for event in events:
            payload = {"resource": "agenttrust.runtime", "event": event}
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    os.replace(temporary_path, target)
    return target
