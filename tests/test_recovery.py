from __future__ import annotations

import json
from pathlib import Path

from agenttrust.runtime.recovery import restore_run
from agenttrust.runtime.trace import TraceRecorder, verify_trace


def test_trace_verification_detects_tampering(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path / "run")
    recorder.append("run_started", run_id="run")
    recorder.append("run_completed", run_id="run")

    assert verify_trace(recorder.trace_path)["valid"] is True

    lines = recorder.trace_path.read_text(encoding="utf-8").splitlines()
    recorder.trace_path.write_text(lines[0].replace("run_started", "tampered") + "\n" + lines[1] + "\n", encoding="utf-8")
    assert verify_trace(recorder.trace_path)["valid"] is False


def test_restore_skips_manifest_paths_outside_project_root(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agenttrust" / "runs" / "run_test"
    backups_dir = run_dir / "backups"
    backups_dir.mkdir(parents=True)
    outside = tmp_path.parent / "outside-restore-target.txt"
    outside.write_text("outside", encoding="utf-8")
    backup = backups_dir / "call_001.bak"
    backup.write_text("polluted", encoding="utf-8")
    manifest = backups_dir / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "run_id": "run_test",
                "tool_call_id": "call_001",
                "path": str(outside),
                "existed": True,
                "backup_path": str(backup),
                "created_at": "2026-07-08T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    actions = restore_run(run_dir)

    assert actions[0]["action"] == "skipped"
    assert actions[0]["reason"] == "restore path escapes project_root"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_restore_skips_backup_paths_outside_run_backups(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agenttrust" / "runs" / "run_test"
    backups_dir = run_dir / "backups"
    backups_dir.mkdir(parents=True)
    target = tmp_path / "tmp" / "demo.txt"
    target.parent.mkdir()
    target.write_text("current", encoding="utf-8")
    outside_backup = tmp_path / "outside-backup.bak"
    outside_backup.write_text("polluted", encoding="utf-8")
    manifest = backups_dir / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "run_id": "run_test",
                "tool_call_id": "call_001",
                "path": str(target),
                "existed": True,
                "backup_path": str(outside_backup),
                "created_at": "2026-07-08T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    actions = restore_run(run_dir)

    assert actions[0]["action"] == "skipped"
    assert actions[0]["reason"] == "backup path escapes run backups"
    assert target.read_text(encoding="utf-8") == "current"
