"""Evidence persistence adapters."""

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder, read_trace, verify_trace
from agenttrust.adapters.evidence.export import export_ndjson
from agenttrust.adapters.evidence.otel import export_otel_trace
from agenttrust.adapters.evidence.approval_journal import JsonlApprovalJournal
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.recovery import BackupRecord, create_backup_for_write, load_backup_records, restore_run
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection, StateRebuildResult, rebuild_state_from_traces

__all__ = [
    "BackupRecord",
    "JsonlApprovalJournal",
    "TraceRecorder",
    "ProjectingTraceRecorder",
    "SQLiteStateProjection",
    "StateRebuildResult",
    "create_backup_for_write",
    "export_ndjson",
    "export_otel_trace",
    "load_backup_records",
    "read_trace",
    "rebuild_state_from_traces",
    "restore_run",
    "verify_trace",
]
