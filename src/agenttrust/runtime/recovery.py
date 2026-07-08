"""Recovery Lite for write_file tool mutations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from agenttrust.schemas import ToolIntent, utc_now_iso
from agenttrust.runtime.trace import TraceRecorder


@dataclass(frozen=True)
class BackupRecord:
    run_id: str
    tool_call_id: str
    path: str
    existed: bool
    backup_path: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "existed": self.existed,
            "backup_path": self.backup_path,
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
    existed = target.exists()
    if existed:
        backup_path = backup_dir / f"{intent.tool_call_id}.bak"
        backup_path.write_bytes(target.read_bytes())
    record = BackupRecord(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        path=str(target),
        existed=existed,
        backup_path=str(backup_path) if backup_path is not None else None,
        created_at=utc_now_iso(),
    )
    manifest = backup_dir / "manifest.jsonl"
    with manifest.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return record


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
                created_at=str(raw["created_at"]),
            )
        )
    return records


def restore_run(run_dir: Path, only_file: str | None = None, dry_run: bool = False) -> list[dict[str, object]]:
    run_dir = run_dir.resolve()
    project_root = _project_root_from_run_dir(run_dir)
    backups_root = (run_dir / "backups").resolve()
    records = load_backup_records(run_dir)
    actions: list[dict[str, object]] = []
    recorder = TraceRecorder(run_dir)
    for record in reversed(records):
        target = Path(record.path).resolve(strict=False)
        if only_file and Path(only_file).name != target.name and str(target) != only_file:
            continue
        action = {
            "path": str(target),
            "existed": record.existed,
            "action": "restore" if record.existed else "delete_created",
            "dry_run": dry_run,
        }
        if not _is_inside(project_root, target):
            skipped = {**action, "action": "skipped", "reason": "restore path escapes project_root"}
            actions.append(skipped)
            recorder.append("restore_skipped", run_id=record.run_id, tool_call_id=record.tool_call_id, **skipped)
            continue
        backup_path = Path(record.backup_path).resolve(strict=False) if record.backup_path else None
        if record.existed and (backup_path is None or not _is_inside(backups_root, backup_path)):
            skipped = {**action, "action": "skipped", "reason": "backup path escapes run backups"}
            actions.append(skipped)
            recorder.append("restore_skipped", run_id=record.run_id, tool_call_id=record.tool_call_id, **skipped)
            continue
        actions.append(action)
        if dry_run:
            recorder.append("restore_preview", run_id=record.run_id, tool_call_id=record.tool_call_id, **action)
            continue
        if record.existed and record.backup_path:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(backup_path.read_bytes())
        elif target.exists():
            target.unlink()
        recorder.append("restore_applied", run_id=record.run_id, tool_call_id=record.tool_call_id, **action)
    return actions


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
