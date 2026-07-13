"""Append-only JSONL evidence storage with a verified incremental trace head."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from agenttrust.adapters.evidence.run_lock import RunLock
from agenttrust.domain.models import utc_now_iso


EVIDENCE_SCHEMA_VERSION = "agenttrust.evidence/v1"
TRACE_HEAD_SCHEMA_VERSION = "agenttrust.trace-head/v1"
TRACE_HEAD_CHECKPOINT_INTERVAL = 64
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_sequence",
        "event_type",
        "subject",
        "payload",
        "previous_hash",
        "event_hash",
    }
)


class TraceRecorder:
    """Persist evidence events with a local checkpoint to avoid repeated full scans."""

    def __init__(
        self,
        run_dir: Path,
        context: dict[str, Any] | None = None,
        run_lock: RunLock | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"
        self.head_path = self.run_dir / "trace-head.json"
        self._context = dict(context or {})
        self._lock = RLock()
        self._run_lock = run_lock or RunLock(self.run_dir)
        self._head_cache: dict[str, Any] | None = None

    def bind(self, **context: Any) -> None:
        """Attach run-scoped governance metadata to subsequent evidence events."""

        with self._lock:
            self._context.update({key: value for key, value in context.items() if value is not None})

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            with self._run_lock:
                head = self._load_verified_head()
                event = self._new_event(event_type, payload, head)
                with self.trace_path.open("a", encoding="utf-8", newline="\n") as trace_file:
                    trace_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
                    trace_file.write("\n")
                    trace_file.flush()
                    os.fsync(trace_file.fileno())
                next_head = self._current_head(head["event_count"] + 1, event["event_hash"])
                self._head_cache = next_head
                if next_head["event_count"] == 1 or next_head["event_count"] % TRACE_HEAD_CHECKPOINT_INTERVAL == 0:
                    self._write_head(next_head)
                return event

    def _new_event(self, event_type: str, payload: Mapping[str, Any], head: Mapping[str, Any]) -> dict[str, Any]:
        context = {**self._context, **payload}
        overwritten_fields = sorted(_ENVELOPE_FIELDS.intersection(context))
        if overwritten_fields:
            raise ValueError(f"evidence payload cannot override envelope fields: {', '.join(overwritten_fields)}")
        run_id = context.get("run_id", self.run_dir.name)
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("evidence events require a non-empty run_id")
        if run_id != self.run_dir.name:
            raise ValueError("evidence event run_id must match the recorder run directory")
        context["run_id"] = run_id
        created_at = context.get("created_at", utc_now_iso())
        if not isinstance(created_at, str) or not created_at:
            raise ValueError("evidence events require a non-empty created_at")
        subject = {
            key: context[key]
            for key in ("actor_id", "agent_id", "session_id", "tool_call_id")
            if context.get(key) is not None
        }
        event = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "event_id": f"evt_{uuid4().hex}",
            "event_sequence": head["event_count"] + 1,
            "event_type": event_type,
            "created_at": created_at,
            **context,
            "subject": subject,
            "payload": dict(payload),
            "previous_hash": head["head_hash"],
        }
        event["event_hash"] = _event_hash(event)
        return event

    def _load_verified_head(self) -> dict[str, Any]:
        if not self.trace_path.exists():
            if self.head_path.exists():
                self.head_path.unlink()
            self._head_cache = None
            return {"event_count": 0, "head_hash": None}
        if self._head_cache is not None and _cached_head_matches_trace(self._head_cache, self.trace_path):
            return self._head_cache
        stored_head = _read_head(self.head_path)
        if stored_head is not None and _head_matches_trace(stored_head, self.trace_path):
            self._head_cache = stored_head
            return stored_head
        rebuilt_head = self._rebuild_head()
        self._head_cache = rebuilt_head
        return rebuilt_head

    def _rebuild_head(self) -> dict[str, Any]:
        events = read_trace(self.trace_path)
        verification = verify_events(events)
        if verification["valid"] is not True:
            raise ValueError(f"cannot append to invalid evidence trace: {verification.get('reason', 'unknown')}")
        event_count = verification.get("event_count")
        head_hash = verification.get("head_hash")
        if isinstance(event_count, bool) or not isinstance(event_count, int):
            raise ValueError("evidence verification returned an invalid event count")
        if head_hash is not None and not isinstance(head_hash, str):
            raise ValueError("evidence verification returned an invalid head hash")
        rebuilt_head = self._current_head(event_count, head_hash)
        self._write_head(rebuilt_head)
        return rebuilt_head

    def _current_head(self, event_count: int, head_hash: str | None) -> dict[str, Any]:
        stat = self.trace_path.stat()
        return {
            "schema_version": TRACE_HEAD_SCHEMA_VERSION,
            "event_count": event_count,
            "head_hash": head_hash,
            "trace_size": stat.st_size,
            "trace_mtime_ns": stat.st_mtime_ns,
        }

    def _write_head(self, payload: Mapping[str, Any]) -> None:
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=self.run_dir, delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.head_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def read_trace(trace_path: Path) -> list[dict[str, Any]]:
    """Read evidence events from a JSONL trace file without changing their raw shape."""

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
    """Read, verify, and migrate evidence into the portable v1 envelope shape."""

    events = read_trace(run_dir / "trace.jsonl")
    verification = verify_events(events)
    if verification["valid"] is not True:
        raise ValueError(f"invalid evidence trace: {verification.get('reason', 'unknown')}")
    normalized = [_normalize_event(event, index) for index, event in enumerate(events, start=1)]
    for event in normalized:
        if event.get("run_id") != run_dir.name:
            raise ValueError("evidence event run_id does not match run directory")
    return normalized


def _read_head(head_path: Path) -> dict[str, Any] | None:
    if not head_path.exists():
        return None
    try:
        payload = json.loads(head_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != TRACE_HEAD_SCHEMA_VERSION:
        return None
    event_count = payload.get("event_count")
    trace_size = payload.get("trace_size")
    trace_mtime_ns = payload.get("trace_mtime_ns")
    head_hash = payload.get("head_hash")
    if (
        isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or event_count < 0
        or isinstance(trace_size, bool)
        or not isinstance(trace_size, int)
        or trace_size < 0
        or isinstance(trace_mtime_ns, bool)
        or not isinstance(trace_mtime_ns, int)
        or (head_hash is not None and not isinstance(head_hash, str))
    ):
        return None
    return payload


def _head_matches_trace(head: Mapping[str, Any], trace_path: Path) -> bool:
    stat = trace_path.stat()
    if head.get("trace_size") != stat.st_size or head.get("trace_mtime_ns") != stat.st_mtime_ns:
        return False
    event_count = head.get("event_count")
    head_hash = head.get("head_hash")
    if event_count == 0:
        return stat.st_size == 0 and head_hash is None
    last_event = _read_last_event(trace_path)
    if last_event is None or last_event.get("event_hash") != head_hash:
        return False
    return last_event.get("event_sequence") == event_count


def _cached_head_matches_trace(head: Mapping[str, Any], trace_path: Path) -> bool:
    """Trust an in-process head after checking that no other writer changed the file."""

    stat = trace_path.stat()
    return head.get("trace_size") == stat.st_size and head.get("trace_mtime_ns") == stat.st_mtime_ns


def _read_last_event(trace_path: Path) -> dict[str, Any] | None:
    with trace_path.open("rb") as trace_file:
        trace_file.seek(0, os.SEEK_END)
        position = trace_file.tell()
        if position == 0:
            return None
        buffer = b""
        while position > 0:
            chunk_size = min(8192, position)
            position -= chunk_size
            trace_file.seek(position)
            buffer = trace_file.read(chunk_size) + buffer
            stripped = buffer.rstrip(b"\r\n")
            separator = stripped.rfind(b"\n")
            if separator >= 0 or position == 0:
                line = stripped[separator + 1 :] if separator >= 0 else stripped
                if not line:
                    return None
                payload = json.loads(line.decode("utf-8"))
                return payload if isinstance(payload, dict) else None
    return None


def _normalize_event(event: Mapping[str, Any], index: int) -> dict[str, Any]:
    normalized = dict(event)
    schema_version = normalized.get("schema_version")
    if schema_version is None:
        normalized.update(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "event_id": f"legacy_{normalized.get('event_hash', index)}",
                "event_sequence": index,
                "subject": {
                    key: normalized[key]
                    for key in ("actor_id", "agent_id", "session_id", "tool_call_id")
                    if normalized.get(key) is not None
                },
                "payload": {
                    key: value
                    for key, value in normalized.items()
                    if key
                    not in {
                        "schema_version",
                        "event_id",
                        "event_sequence",
                        "event_type",
                        "created_at",
                        "subject",
                        "payload",
                        "previous_hash",
                        "event_hash",
                    }
                },
            }
        )
        return normalized
    if schema_version != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"unsupported evidence schema version: {schema_version}")
    if (
        not isinstance(normalized.get("event_id"), str)
        or isinstance(normalized.get("event_sequence"), bool)
        or normalized.get("event_sequence") != index
        or not isinstance(normalized.get("event_type"), str)
        or not isinstance(normalized.get("created_at"), str)
        or not isinstance(normalized.get("run_id"), str)
        or not isinstance(normalized.get("subject"), dict)
        or not isinstance(normalized.get("payload"), dict)
    ):
        raise ValueError("invalid evidence v1 envelope")
    return normalized


def _event_hash(event: Mapping[str, Any]) -> str:
    canonical = {key: value for key, value in event.items() if key != "event_hash"}
    payload = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
