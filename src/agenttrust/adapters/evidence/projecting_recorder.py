"""Evidence recorder adapter that keeps a SQLite projection in sync."""

from __future__ import annotations

import sqlite3
from typing import Any

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection


class ProjectingTraceRecorder:
    """Append JSONL evidence first, then project recognized state events to SQLite."""

    def __init__(self, recorder: TraceRecorder, projection: SQLiteStateProjection) -> None:
        self._recorder = recorder
        self._projection = projection

    @property
    def trace_path(self):
        return self._recorder.trace_path

    def bind(self, **context: Any) -> None:
        self._recorder.bind(**context)

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = self._recorder.append(event_type, **payload)
        try:
            self._projection.apply_event(event)
        except (sqlite3.Error, ValueError):
            # SQLite is a disposable cache; rebuild it from authoritative JSONL.
            try:
                self._projection.rebuild()
            except (OSError, sqlite3.Error, ValueError):
                pass
        return event
