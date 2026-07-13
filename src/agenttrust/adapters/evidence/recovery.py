"""JSONL-backed recovery adapter for local file mutations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder, read_verified_events
from agenttrust.adapters.evidence.run_lock import RunLock
from agenttrust.domain.models import ToolIntent, ToolResult, utc_now_iso


@dataclass(frozen=True)
class BackupRecord:
    run_id: str
    tool_call_id: str
    path: str
    existed: bool
    backup_path: str | None
    backup_sha256: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "existed": self.existed,
            "backup_path": self.backup_path,
            "backup_sha256": self.backup_sha256,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class WriteRecoveryCheckpoint:
    """A restore point bound to a successful, observed file write."""

    run_id: str
    tool_call_id: str
    path: str
    existed: bool
    backup_path: str | None
    backup_sha256: str | None
    post_write_sha256: str
    result_output_digest: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "existed": self.existed,
            "backup_path": self.backup_path,
            "backup_sha256": self.backup_sha256,
            "post_write_sha256": self.post_write_sha256,
            "result_output_digest": self.result_output_digest,
            "created_at": self.created_at,
        }


def create_backup_for_write(intent: ToolIntent, project_root: Path, run_dir: Path) -> BackupRecord | None:
    if intent.tool_name != "write_file":
        return None
    path_arg = intent.arguments.get("path")
    if not isinstance(path_arg, str) or not path_arg:
        return None
    target = (project_root / path_arg).resolve()
    backup_dir = run_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    backup_sha256: str | None = None
    existed = target.exists()
    if existed:
        backup_path = backup_dir / f"{intent.tool_call_id}.bak"
        backup_bytes = target.read_bytes()
        backup_path.write_bytes(backup_bytes)
        backup_sha256 = _sha256(backup_bytes)
    record = BackupRecord(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        path=str(target),
        existed=existed,
        backup_path=str(backup_path) if backup_path is not None else None,
        backup_sha256=backup_sha256,
        created_at=utc_now_iso(),
    )
    manifest = backup_dir / "manifest.jsonl"
    with manifest.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return record


def bind_successful_write(
    intent: ToolIntent,
    result: ToolResult,
    checkpoint: object,
    project_root: Path,
) -> WriteRecoveryCheckpoint | None:
    """Confirm the actual post-write bytes before making a backup recoverable."""

    if (
        intent.tool_name != "write_file"
        or result.status != "ok"
        or not isinstance(checkpoint, BackupRecord)
        or result.output_digest is None
    ):
        return None
    target = Path(checkpoint.path).resolve(strict=False)
    if not _is_inside(project_root.resolve(), target) or not target.is_file():
        return None
    post_write_sha256 = _sha256(target.read_bytes())
    if post_write_sha256 != result.output_digest:
        return None
    return WriteRecoveryCheckpoint(
        run_id=checkpoint.run_id,
        tool_call_id=checkpoint.tool_call_id,
        path=checkpoint.path,
        existed=checkpoint.existed,
        backup_path=checkpoint.backup_path,
        backup_sha256=checkpoint.backup_sha256,
        post_write_sha256=post_write_sha256,
        result_output_digest=result.output_digest,
        created_at=utc_now_iso(),
    )


def load_backup_records(run_dir: Path) -> list[BackupRecord]:
    manifest = run_dir / "backups" / "manifest.jsonl"
    if not manifest.exists():
        return []
    records: list[BackupRecord] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        records.append(
            BackupRecord(
                run_id=str(raw["run_id"]),
                tool_call_id=str(raw["tool_call_id"]),
                path=str(raw["path"]),
                existed=bool(raw["existed"]),
                backup_path=str(raw["backup_path"]) if raw.get("backup_path") else None,
                backup_sha256=str(raw["backup_sha256"]) if raw.get("backup_sha256") else None,
                created_at=str(raw["created_at"]),
            )
        )
    return records


def restore_run(
    run_dir: Path,
    only_file: str | None = None,
    dry_run: bool = True,
    force: bool = False,
) -> list[dict[str, object]]:
    run_dir = run_dir.resolve()
    with RunLock(run_dir) as operation_lock:
        return _restore_run_locked(run_dir, only_file, dry_run, force, operation_lock)


def _restore_run_locked(
    run_dir: Path,
    only_file: str | None,
    dry_run: bool,
    force: bool,
    operation_lock: RunLock,
) -> list[dict[str, object]]:
    project_root = _project_root_from_run_dir(run_dir)
    backups_root = (run_dir / "backups").resolve()
    records = _recovery_checkpoints_from_verified_trace(run_dir)
    actions: list[dict[str, object]] = []
    recorder = TraceRecorder(run_dir, run_lock=operation_lock)
    for record in reversed(records):
        target = Path(record.path).resolve(strict=False)
        if only_file and Path(only_file).name != target.name and str(target) != only_file:
            continue
        action = {
            "path": str(target),
            "existed": record.existed,
            "action": "restore" if record.existed else "delete_created",
            "dry_run": dry_run,
            "force": force,
        }
        if not _is_inside(project_root, target):
            skipped = {**action, "action": "skipped", "reason": "restore path escapes project_root"}
            actions.append(skipped)
            recorder.append("restore_skipped", run_id=record.run_id, tool_call_id=record.tool_call_id, **skipped)
            continue
        backup_path = Path(record.backup_path).resolve(strict=False) if record.backup_path else None
        expected_backup_path = (backups_root / f"{record.tool_call_id}.bak").resolve()
        if record.existed and (
            backup_path is None
            or backup_path != expected_backup_path
            or not _is_inside(backups_root, backup_path)
        ):
            skipped = {**action, "action": "skipped", "reason": "backup path escapes run backups"}
            actions.append(skipped)
            recorder.append("restore_skipped", run_id=record.run_id, tool_call_id=record.tool_call_id, **skipped)
            continue
        if record.existed and (backup_path is None or not backup_path.is_file()):
            skipped = {**action, "action": "skipped", "reason": "backup file is unavailable"}
            actions.append(skipped)
            recorder.append("restore_skipped", run_id=record.run_id, tool_call_id=record.tool_call_id, **skipped)
            continue
        if record.existed:
            assert backup_path is not None
            if _sha256(backup_path.read_bytes()) != record.backup_sha256:
                skipped = {**action, "action": "skipped", "reason": "backup digest mismatch"}
                actions.append(skipped)
                recorder.append("restore_skipped", run_id=record.run_id, tool_call_id=record.tool_call_id, **skipped)
                continue
        if not force and _post_write_state_changed(target, record.post_write_sha256):
            conflict = {**action, "action": "skipped", "reason": "target changed after governed write"}
            actions.append(conflict)
            recorder.append("restore_conflict", run_id=record.run_id, tool_call_id=record.tool_call_id, **conflict)
            continue
        actions.append(action)
        if dry_run:
            recorder.append("restore_preview", run_id=record.run_id, tool_call_id=record.tool_call_id, **action)
            continue
        if record.existed and record.backup_path:
            assert backup_path is not None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(backup_path.read_bytes())
        elif target.exists():
            target.unlink()
        recorder.append("restore_applied", run_id=record.run_id, tool_call_id=record.tool_call_id, **action)
    return actions


def _recovery_checkpoints_from_verified_trace(run_dir: Path) -> list[WriteRecoveryCheckpoint]:
    events = read_verified_events(run_dir)
    successful_results: dict[str, str] = {}
    for event in events:
        if event.get("event_type") != "tool_result" or event.get("status") != "ok":
            continue
        tool_call_id = _required_text(event, "tool_call_id")
        output_digest = _required_text(event, "output_digest")
        successful_results[tool_call_id] = output_digest

    records: list[WriteRecoveryCheckpoint] = []
    for event in events:
        if event.get("event_type") != "write_recovery_checkpoint":
            continue
        record = _recovery_checkpoint_from_evidence(event)
        if record.run_id != run_dir.name:
            raise ValueError("recovery checkpoint run_id does not match run directory")
        if successful_results.get(record.tool_call_id) != record.result_output_digest:
            raise ValueError("recovery checkpoint is not bound to a successful tool result")
        records.append(record)
    return records


def _recovery_checkpoint_from_evidence(event: Mapping[str, object]) -> WriteRecoveryCheckpoint:
    existed = event.get("existed")
    if not isinstance(existed, bool):
        raise ValueError("recovery checkpoint requires a boolean existed value")
    backup_path = _optional_text(event, "backup_path")
    backup_sha256 = _optional_text(event, "backup_sha256")
    if existed and (backup_path is None or backup_sha256 is None):
        raise ValueError("existing recovery checkpoint requires a path and sha256 digest")
    if not existed and (backup_path is not None or backup_sha256 is not None):
        raise ValueError("new-file recovery checkpoint must not include backup content")
    post_write_sha256 = _required_text(event, "post_write_sha256")
    result_output_digest = _required_text(event, "result_output_digest")
    if post_write_sha256 != result_output_digest:
        raise ValueError("recovery checkpoint post-write digest must match tool result digest")
    return WriteRecoveryCheckpoint(
        run_id=_required_text(event, "run_id"),
        tool_call_id=_required_text(event, "tool_call_id"),
        path=_required_text(event, "path"),
        existed=existed,
        backup_path=backup_path,
        backup_sha256=backup_sha256,
        post_write_sha256=post_write_sha256,
        result_output_digest=result_output_digest,
        created_at=_required_text(event, "created_at"),
    )


def _post_write_state_changed(target: Path, expected_sha256: str) -> bool:
    if not target.is_file():
        return True
    return _sha256(target.read_bytes()) != expected_sha256


def _project_root_from_run_dir(run_dir: Path) -> Path:
    try:
        if run_dir.parent.name == "runs" and run_dir.parent.parent.name == ".agenttrust":
            return run_dir.parent.parent.parent.resolve()
    except IndexError:
        pass
    return run_dir.parent.resolve()


def _is_inside(root: Path, path: Path) -> bool:
    root_norm = os.path.normcase(os.path.abspath(str(root)))
    path_norm = os.path.normcase(os.path.abspath(str(path)))
    try:
        return os.path.commonpath([root_norm, path_norm]) == root_norm
    except ValueError:
        return False


def _sha256(content: bytes) -> str:
    return "sha256:" + sha256(content).hexdigest()


def _required_text(event: Mapping[str, object], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"backup evidence requires a non-empty {key}")
    return value


def _optional_text(event: Mapping[str, object], key: str) -> str | None:
    value = event.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"backup evidence requires {key} to be a non-empty string or null")
    return value
