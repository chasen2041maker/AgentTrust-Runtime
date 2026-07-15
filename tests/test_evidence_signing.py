from __future__ import annotations

import json
from pathlib import Path

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder, _event_hash
from agenttrust.adapters.evidence.signing import (
    ANCHOR_FILE_NAME,
    generate_signing_key_pair,
    sign_verified_trace,
    verify_trace_anchor,
)
from agenttrust.interfaces.cli import main


def _make_trace(run_dir: Path) -> None:
    recorder = TraceRecorder(run_dir)
    recorder.append("session_created", actor_id="alice")
    recorder.append("tool_result", tool_name="read_file", status="ok")


def _rewrite_hash_chain(trace_path: Path, events: list[dict[str, object]]) -> None:
    previous_hash: str | None = None
    for event in events:
        event["previous_hash"] = previous_hash
        event["event_hash"] = _event_hash(event)
        previous_hash = event["event_hash"]
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def test_signing_key_pair_is_encrypted_and_anchor_verifies_with_pinned_public_key(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _make_trace(run_dir)
    private_key = tmp_path / "keys" / "evidence-private.pem"
    public_key = tmp_path / "keys" / "evidence-public.pem"

    key_pair = generate_signing_key_pair(private_key, public_key, passphrase="correct horse battery staple")
    anchor_path = sign_verified_trace(run_dir, private_key, passphrase="correct horse battery staple")

    assert anchor_path == run_dir / ANCHOR_FILE_NAME
    assert "ENCRYPTED PRIVATE KEY" in private_key.read_text(encoding="utf-8")
    assert key_pair["key_id"].startswith("sha256:")
    verification = verify_trace_anchor(run_dir, public_key)
    assert verification["valid"] is True
    assert verification["event_count"] == 2
    assert verification["key_id"] == key_pair["key_id"]


def test_anchor_detects_a_rewritten_but_hash_valid_trace(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _make_trace(run_dir)
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    generate_signing_key_pair(private_key, public_key, passphrase="passphrase")
    sign_verified_trace(run_dir, private_key, passphrase="passphrase")

    trace_path = run_dir / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    events[0]["event_type"] = "rewritten_session_created"
    _rewrite_hash_chain(trace_path, events)

    assert verify_trace_anchor(run_dir, public_key) == {"valid": False, "reason": "trace_head_changed"}


def test_anchor_signature_and_pinned_key_are_both_verified(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _make_trace(run_dir)
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    second_private_key = tmp_path / "second-private.pem"
    second_public_key = tmp_path / "second-public.pem"
    generate_signing_key_pair(private_key, public_key, passphrase="passphrase")
    generate_signing_key_pair(second_private_key, second_public_key, passphrase="second-passphrase")
    sign_verified_trace(run_dir, private_key, passphrase="passphrase")

    anchor_path = run_dir / ANCHOR_FILE_NAME
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["payload"]["signed_at"] = "2000-01-01T00:00:00Z"
    anchor_path.write_text(json.dumps(anchor), encoding="utf-8")
    assert verify_trace_anchor(run_dir, public_key) == {"valid": False, "reason": "signature_invalid"}

    sign_verified_trace(run_dir, private_key, passphrase="passphrase")
    assert verify_trace_anchor(run_dir, second_public_key) == {"valid": False, "reason": "public_key_id_mismatch"}


def test_evidence_anchor_cli_uses_a_passphrase_environment_variable(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTTRUST_TEST_SIGNING_KEY", "test-only-passphrase")
    assert main(["run-fixture", "verified_answer", "--mode", "test"]) == 0
    run_id = next(line.split("=", 1)[1] for line in capsys.readouterr().out.splitlines() if line.startswith("run_id="))

    assert main(
        [
            "evidence",
            "keygen",
            "--private-key",
            "keys/evidence-private.pem",
            "--public-key",
            "keys/evidence-public.pem",
            "--passphrase-env",
            "AGENTTRUST_TEST_SIGNING_KEY",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["key_id"].startswith("sha256:")

    assert main(
        [
            "evidence",
            "anchor",
            run_id,
            "--private-key",
            "keys/evidence-private.pem",
            "--passphrase-env",
            "AGENTTRUST_TEST_SIGNING_KEY",
        ]
    ) == 0
    assert Path(capsys.readouterr().out.strip()).name == ANCHOR_FILE_NAME

    assert main(["evidence", "verify-anchor", run_id, "--public-key", "keys/evidence-public.pem"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
