"""SQLite projection of governed-session evidence events."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator, Mapping, cast

from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.domain.lifecycle import (
    SESSION_STATUSES,
    TOOL_CALL_STATUSES,
    SessionStatus,
    ToolCallStatus,
    assert_session_transition,
    assert_tool_call_transition,
)


@dataclass(frozen=True)
class StateRebuildResult:
    """Summary of rebuilding the derived SQLite state from JSONL evidence."""

    traces_scanned: int
    runs_projected: int
    events_projected: int

    def to_dict(self) -> dict[str, int]:
        return {
            "traces_scanned": self.traces_scanned,
            "runs_projected": self.runs_projected,
            "events_projected": self.events_projected,
        }


class SQLiteStateProjection:
    """Maintain queryable session state while JSONL remains the source of truth."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.db_path = self.project_root / ".agenttrust" / "state.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection():
            pass

    def apply_event(self, event: Mapping[str, object]) -> bool:
        """Apply one hash-linked evidence event once, returning whether it changed state."""

        event_type = _required_text(event, "event_type")
        event_hash = _required_text(event, "event_hash")
        handlers = {
            "session_created": self._project_session_created,
            "session_status_changed": self._project_session_status,
            "tool_call_requested": self._project_tool_call_requested,
            "tool_call_status_changed": self._project_tool_call_status,
            "approval_requested": self._project_approval_requested,
            "approval_decided": self._project_approval_decided,
        }
        handler = handlers.get(event_type)
        if handler is None:
            return False

        with self._connection() as connection:
            existing = connection.execute(
                "SELECT 1 FROM projection_events WHERE event_hash = ?", (event_hash,)
            ).fetchone()
            if existing is not None:
                return False
            handler(connection, event, event_hash)
            connection.execute(
                "INSERT INTO projection_events (event_hash, run_id, event_type, created_at) VALUES (?, ?, ?, ?)",
                (
                    event_hash,
                    _required_text(event, "run_id"),
                    event_type,
                    _required_text(event, "created_at"),
                ),
            )
        return True

    def rebuild(self) -> StateRebuildResult:
        """Recreate derived state only from verified JSONL traces."""

        trace_paths = sorted((self.project_root / ".agenttrust" / "runs").glob("*/trace.jsonl"))
        for trace_path in trace_paths:
            verification = verify_trace(trace_path)
            if verification["valid"] is not True:
                reason = verification.get("reason", "unknown")
                raise ValueError(f"cannot rebuild state from invalid trace {trace_path}: {reason}")

        self.reset()
        runs_projected = 0
        events_projected = 0
        for trace_path in trace_paths:
            projected_for_trace = 0
            for event in read_trace(trace_path):
                if self.apply_event(event):
                    projected_for_trace += 1
            if projected_for_trace:
                runs_projected += 1
                events_projected += projected_for_trace
        return StateRebuildResult(
            traces_scanned=len(trace_paths),
            runs_projected=runs_projected,
            events_projected=events_projected,
        )

    def reset(self) -> None:
        """Clear every derived table without touching JSONL evidence."""

        with self._connection() as connection:
            connection.execute("DELETE FROM approvals")
            connection.execute("DELETE FROM tool_calls")
            connection.execute("DELETE FROM sessions")
            connection.execute("DELETE FROM projection_events")

    def get_session(self, run_id: str) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_dict(row)

    def list_tool_calls(self, run_id: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_approvals(self, run_id: str | None = None) -> list[dict[str, object]]:
        with self._connection() as connection:
            if run_id is None:
                rows = connection.execute("SELECT * FROM approvals ORDER BY requested_at").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM approvals WHERE run_id = ? ORDER BY requested_at", (run_id,)
                ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_approval(self, approval_id: str) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return _row_to_dict(row)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _project_session_created(
        self, connection: sqlite3.Connection, event: Mapping[str, object], event_hash: str
    ) -> None:
        run_id = _required_text(event, "run_id")
        if connection.execute("SELECT 1 FROM sessions WHERE run_id = ?", (run_id,)).fetchone() is not None:
            raise ValueError(f"session already exists for run: {run_id}")
        status = _required_text(event, "status")
        if status != "created":
            raise ValueError(f"session creation must have created status, received: {status}")
        if status not in SESSION_STATUSES:
            raise ValueError(f"invalid session status in evidence: {status}")
        connection.execute(
            """
            INSERT INTO sessions (
                run_id, session_id, actor_id, agent_id, policy_version, status,
                created_at, updated_at, source_event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                _required_text(event, "session_id"),
                _required_text(event, "actor_id"),
                _optional_text(event, "agent_id"),
                _optional_text(event, "policy_version"),
                status,
                _required_text(event, "created_at"),
                _required_text(event, "updated_at"),
                event_hash,
            ),
        )

    def _project_session_status(
        self, connection: sqlite3.Connection, event: Mapping[str, object], event_hash: str
    ) -> None:
        status = _required_text(event, "status")
        if status not in SESSION_STATUSES:
            raise ValueError(f"invalid session status in evidence: {status}")
        run_id = _required_text(event, "run_id")
        row = connection.execute("SELECT status FROM sessions WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"session status event references unknown run: {run_id}")
        current_status = row["status"]
        if not isinstance(current_status, str):
            raise ValueError(f"session projection has an invalid status for run: {run_id}")
        assert_session_transition(cast(SessionStatus, current_status), cast(SessionStatus, status))
        cursor = connection.execute(
            "UPDATE sessions SET status = ?, updated_at = ?, source_event_hash = ? WHERE run_id = ?",
            (status, _required_text(event, "updated_at"), event_hash, run_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"session status event references unknown run: {run_id}")

    def _project_tool_call_requested(
        self, connection: sqlite3.Connection, event: Mapping[str, object], event_hash: str
    ) -> None:
        status = _required_text(event, "status")
        if status != "requested":
            raise ValueError(f"tool call request must have requested status, received: {status}")
        connection.execute(
            """
            INSERT INTO tool_calls (
                run_id, tool_call_id, session_id, sequence, tool_name, arguments_digest,
                policy_rule_id, status, requested_at, updated_at, source_event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _required_text(event, "run_id"),
                _required_text(event, "tool_call_id"),
                _required_text(event, "session_id"),
                _required_integer(event, "sequence"),
                _required_text(event, "tool_name"),
                _required_text(event, "arguments_digest"),
                _optional_text(event, "policy_rule_id"),
                status,
                _required_text(event, "requested_at"),
                _required_text(event, "updated_at"),
                event_hash,
            ),
        )

    def _project_tool_call_status(
        self, connection: sqlite3.Connection, event: Mapping[str, object], event_hash: str
    ) -> None:
        status = _required_text(event, "status")
        if status not in TOOL_CALL_STATUSES:
            raise ValueError(f"invalid tool call status in evidence: {status}")
        run_id = _required_text(event, "run_id")
        tool_call_id = _required_text(event, "tool_call_id")
        row = connection.execute(
            "SELECT status FROM tool_calls WHERE run_id = ? AND tool_call_id = ?", (run_id, tool_call_id)
        ).fetchone()
        if row is None:
            raise ValueError(f"tool call status event references unknown call: {run_id}/{tool_call_id}")
        current_status = row["status"]
        if not isinstance(current_status, str):
            raise ValueError(f"tool call projection has an invalid status for call: {run_id}/{tool_call_id}")
        assert_tool_call_transition(cast(ToolCallStatus, current_status), cast(ToolCallStatus, status))
        cursor = connection.execute(
            """
            UPDATE tool_calls
            SET status = ?, updated_at = ?, source_event_hash = ?
            WHERE run_id = ? AND tool_call_id = ?
            """,
            (
                status,
                _required_text(event, "updated_at"),
                event_hash,
                run_id,
                tool_call_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"tool call status event references unknown call: {run_id}/{tool_call_id}")

    def _project_approval_requested(
        self, connection: sqlite3.Connection, event: Mapping[str, object], event_hash: str
    ) -> None:
        connection.execute(
            """
            INSERT INTO approvals (
                approval_id, run_id, tool_call_id, tool_name, arguments_digest, policy_rule_id,
                reason, requested_at, expires_at, approver_id, decision, decision_reason,
                decided_at, source_event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending', NULL, NULL, ?)
            """,
            (
                _required_text(event, "approval_id"),
                _required_text(event, "run_id"),
                _required_text(event, "tool_call_id"),
                _required_text(event, "tool_name"),
                _required_text(event, "arguments_digest"),
                _optional_text(event, "policy_rule_id"),
                _required_text(event, "reason"),
                _required_text(event, "requested_at"),
                _optional_text(event, "expires_at"),
                event_hash,
            ),
        )

    def _project_approval_decided(
        self, connection: sqlite3.Connection, event: Mapping[str, object], event_hash: str
    ) -> None:
        decision = _required_text(event, "decision")
        if decision not in {"approved", "denied"}:
            raise ValueError(f"invalid approval decision in evidence: {decision}")
        cursor = connection.execute(
            """
            UPDATE approvals
            SET approver_id = ?, decision = ?, decision_reason = ?, decided_at = ?, source_event_hash = ?
            WHERE approval_id = ? AND arguments_digest = ? AND decision = 'pending'
            """,
            (
                _required_text(event, "approver_id"),
                decision,
                _required_text(event, "decision_reason"),
                _required_text(event, "decided_at"),
                event_hash,
                _required_text(event, "approval_id"),
                _required_text(event, "arguments_digest"),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(
                "approval decision does not match a pending approval and arguments digest: "
                f"{_required_text(event, 'approval_id')}"
            )


def rebuild_state_from_traces(project_root: Path) -> StateRebuildResult:
    """Convenience entry point for rebuilding `.agenttrust/state.db`."""

    return SQLiteStateProjection(project_root).rebuild()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            run_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            agent_id TEXT,
            policy_version TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_event_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            run_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            arguments_digest TEXT NOT NULL,
            policy_rule_id TEXT,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_event_hash TEXT NOT NULL,
            PRIMARY KEY (run_id, tool_call_id),
            FOREIGN KEY (run_id) REFERENCES sessions(run_id)
        );

        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments_digest TEXT NOT NULL,
            policy_rule_id TEXT,
            reason TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            expires_at TEXT,
            approver_id TEXT,
            decision TEXT NOT NULL,
            decision_reason TEXT,
            decided_at TEXT,
            source_event_hash TEXT NOT NULL,
            FOREIGN KEY (run_id, tool_call_id) REFERENCES tool_calls(run_id, tool_call_id)
        );

        CREATE TABLE IF NOT EXISTS projection_events (
            event_hash TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS tool_calls_by_run ON tool_calls(run_id, sequence);
        CREATE INDEX IF NOT EXISTS approvals_by_run ON approvals(run_id, requested_at);
        """
    )


def _required_text(event: Mapping[str, object], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evidence event requires a non-empty string {key}")
    return value


def _optional_text(event: Mapping[str, object], key: str) -> str | None:
    value = event.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evidence event requires {key} to be a non-empty string or null")
    return value


def _required_integer(event: Mapping[str, object], key: str) -> int:
    value = event.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"evidence event requires a positive integer {key}")
    return value


def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}
