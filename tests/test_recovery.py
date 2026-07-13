from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from agenttrust.runtime.recovery import restore_run
from agenttrust.runtime.trace import TraceRecorder, verify_trace
from agenttrust import AgentTrustRuntime


def _backup_digest(content: bytes) -> str:
    return "sha256:" + sha256(content).hexdigest()


def _record_recovery_checkpoint(run_dir: Path, payload: dict[str, object]) -> None:
    target = Path(str(payload["path"]))
    post_write_sha256 = _backup_digest(target.read_bytes())
    checkpoint = {
        **payload,
        "post_write_sha256": post_write_sha256,
        "result_output_digest": post_write_sha256,
    }
    recorder = TraceRecorder(run_dir)
    recorder.append(
        "tool_result",
        run_id=checkpoint["run_id"],
        tool_call_id=checkpoint["tool_call_id"],
        tool_name="write_file",
        status="ok",
        output_digest=post_write_sha256,
    )
    recorder.append("write_recovery_checkpoint", **checkpoint)


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
                "backup_sha256": _backup_digest(b"polluted"),
                "created_at": "2026-07-08T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _record_recovery_checkpoint(
        run_dir,
        {
            "run_id": "run_test",
            "tool_call_id": "call_001",
            "path": str(outside),
            "existed": True,
            "backup_path": str(backup),
            "backup_sha256": _backup_digest(b"polluted"),
            "created_at": "2026-07-08T00:00:00Z",
        },
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
                "backup_sha256": _backup_digest(b"polluted"),
                "created_at": "2026-07-08T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _record_recovery_checkpoint(
        run_dir,
        {
            "run_id": "run_test",
            "tool_call_id": "call_001",
            "path": str(target),
            "existed": True,
            "backup_path": str(outside_backup),
            "backup_sha256": _backup_digest(b"polluted"),
            "created_at": "2026-07-08T00:00:00Z",
        },
    )

    actions = restore_run(run_dir)

    assert actions[0]["action"] == "skipped"
    assert actions[0]["reason"] == "backup path escapes run backups"
    assert target.read_text(encoding="utf-8") == "current"


def test_restore_uses_verified_backup_evidence_not_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agenttrust" / "runs" / "run_test"
    backups_dir = run_dir / "backups"
    backups_dir.mkdir(parents=True)
    target = tmp_path / "tmp" / "demo.txt"
    target.parent.mkdir()
    target.write_text("changed", encoding="utf-8")
    backup = backups_dir / "call_001.bak"
    backup.write_text("original", encoding="utf-8")
    _record_recovery_checkpoint(
        run_dir,
        {
            "run_id": "run_test",
            "tool_call_id": "call_001",
            "path": str(target),
            "existed": True,
            "backup_path": str(backup),
            "backup_sha256": _backup_digest(b"original"),
            "created_at": "2026-07-08T00:00:00Z",
        },
    )
    (backups_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run_test",
                "tool_call_id": "call_999",
                "path": str(tmp_path.parent / "manifest-poison.txt"),
                "existed": False,
                "backup_path": None,
                "backup_sha256": None,
                "created_at": "2026-07-08T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    actions = restore_run(run_dir, dry_run=False)

    assert actions == [
        {
            "path": str(target.resolve()),
            "existed": True,
            "action": "restore",
            "dry_run": False,
            "force": False,
        }
    ]
    assert target.read_text(encoding="utf-8") == "original"


def test_restore_rejects_tampered_trace_and_backup_bytes(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agenttrust" / "runs" / "run_test"
    backups_dir = run_dir / "backups"
    backups_dir.mkdir(parents=True)
    target = tmp_path / "tmp" / "demo.txt"
    target.parent.mkdir()
    target.write_text("changed", encoding="utf-8")
    backup = backups_dir / "call_001.bak"
    backup.write_text("original", encoding="utf-8")
    _record_recovery_checkpoint(
        run_dir,
        {
            "run_id": "run_test",
            "tool_call_id": "call_001",
            "path": str(target),
            "existed": True,
            "backup_path": str(backup),
            "backup_sha256": _backup_digest(b"original"),
            "created_at": "2026-07-08T00:00:00Z",
        },
    )

    backup.write_text("poisoned", encoding="utf-8")
    actions = restore_run(run_dir)
    assert actions[0]["reason"] == "backup digest mismatch"
    assert target.read_text(encoding="utf-8") == "changed"

    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text(trace_path.read_text(encoding="utf-8").replace("write_recovery_checkpoint", "tampered", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid evidence"):
        restore_run(run_dir)


def test_restore_preserves_user_changes_unless_forced(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agenttrust" / "runs" / "run_test"
    backups_dir = run_dir / "backups"
    backups_dir.mkdir(parents=True)
    target = tmp_path / "tmp" / "demo.txt"
    target.parent.mkdir()
    target.write_text("changed by agent", encoding="utf-8")
    backup = backups_dir / "call_001.bak"
    backup.write_text("original", encoding="utf-8")
    _record_recovery_checkpoint(
        run_dir,
        {
            "run_id": "run_test",
            "tool_call_id": "call_001",
            "path": str(target),
            "existed": True,
            "backup_path": str(backup),
            "backup_sha256": _backup_digest(b"original"),
            "created_at": "2026-07-08T00:00:00Z",
        },
    )
    target.write_text("edited after agent run", encoding="utf-8")

    actions = restore_run(run_dir, dry_run=False)

    assert actions[0]["action"] == "skipped"
    assert actions[0]["reason"] == "target changed after governed write"
    assert target.read_text(encoding="utf-8") == "edited after agent run"
    assert restore_run(run_dir, dry_run=False, force=True)[0]["action"] == "restore"
    assert target.read_text(encoding="utf-8") == "original"


def test_restore_does_not_delete_a_user_modified_new_file(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agenttrust" / "runs" / "run_test"
    target = tmp_path / "tmp" / "created.txt"
    target.parent.mkdir()
    target.write_text("agent version", encoding="utf-8")
    _record_recovery_checkpoint(
        run_dir,
        {
            "run_id": "run_test",
            "tool_call_id": "call_001",
            "path": str(target),
            "existed": False,
            "backup_path": None,
            "backup_sha256": None,
            "created_at": "2026-07-08T00:00:00Z",
        },
    )
    target.write_text("user version", encoding="utf-8")

    actions = restore_run(run_dir, dry_run=False)

    assert actions[0]["action"] == "skipped"
    assert actions[0]["reason"] == "target changed after governed write"
    assert target.read_text(encoding="utf-8") == "user version"


def test_failed_write_does_not_create_a_recovery_checkpoint(tmp_path: Path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice") as session:
        tool_run = session.execute("write_file", {"path": "failed.txt", "content": 42})

    assert tool_run.outcome.result is not None
    assert tool_run.outcome.result.status == "error"
    events = [json.loads(line) for line in (session.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "write_recovery_checkpoint" not in [event["event_type"] for event in events]
    assert restore_run(session.run_dir) == []
