from __future__ import annotations

import json
from pathlib import Path

from agenttrust.cli import main


def _run_id_from_output(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("run_id="):
            return line.split("=", 1)[1]
    raise AssertionError(f"run_id not found in output: {output}")


def _events_for_run(root: Path, run_id: str) -> list[dict[str, object]]:
    trace_path = root / ".agenttrust" / "runs" / run_id / "trace.jsonl"
    return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]


def test_init_creates_agenttrust_directory(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["init"])

    assert exit_code == 0
    assert (tmp_path / ".agenttrust" / "policy.yaml").exists()
    assert (tmp_path / ".agenttrust" / "runs").is_dir()
    assert "Initialized" in capsys.readouterr().out


def test_run_fixture_records_tool_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    exit_code = main(["run-fixture", "verified_answer"])

    assert exit_code == 0
    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)

    assert "permission_decision" in [event["event_type"] for event in events]
    assert "sandbox_decision" in [event["event_type"] for event in events]
    assert "fact_mapped" in [event["event_type"] for event in events]
    assert "groundguard_check" in [event["event_type"] for event in events]
    assert events[1]["tool_name"] == "shell"
    assert any(event.get("status") == "ok" for event in events)


def test_replay_prints_timeline(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    assert main(["run-fixture", "verified_answer"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)

    exit_code = main(["replay", run_id])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "run_started" in output
    assert "permission_decision: shell allow -> allow" in output
    assert "tool_result: shell -> ok" in output


def test_report_writes_markdown(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    assert main(["run-fixture", "verified_answer"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)

    exit_code = main(["report", run_id])

    assert exit_code == 0
    report_path = Path(capsys.readouterr().out.strip())
    assert report_path.exists()
    assert "# AgentTrust Run Report" in report_path.read_text(encoding="utf-8")


def test_html_report_writes_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    assert main(["run-fixture", "verified_answer"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)

    exit_code = main(["report", run_id, "--format", "html"])

    assert exit_code == 0
    report_path = Path(capsys.readouterr().out.strip())
    assert report_path.exists()
    assert "<!doctype html>" in report_path.read_text(encoding="utf-8")


def test_blocked_secret_is_denied_before_execution(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    assert main(["run-fixture", "blocked_secret"]) == 0

    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    permission = next(event for event in events if event["event_type"] == "permission_decision")
    assert permission["effect"] == "deny"
    assert permission["final_effect"] == "deny"
    assert not any(event["event_type"] == "tool_result" for event in events)


def test_ask_noninteractive_denies_without_execution(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()

    assert main(["run-fixture", "ask_noninteractive", "--non-interactive"]) == 0

    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    permission = next(event for event in events if event["event_type"] == "permission_decision")
    assert permission["effect"] == "ask"
    assert permission["final_effect"] == "deny"
    assert permission["reason"] == "approval_required"
    assert not (tmp_path / "src" / "app.py").exists()


def test_test_mode_approves_ask_and_executes_write(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()

    assert main(["run-fixture", "ask_noninteractive", "--mode", "test"]) == 0

    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    permission = next(event for event in events if event["event_type"] == "permission_decision")
    assert permission["effect"] == "ask"
    assert permission["final_effect"] == "allow"
    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == "changed"


def test_fact_fixtures_record_expected_coverage_statuses(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    expected = {
        "verified_answer": "verified",
        "contradicted_answer": "contradicted",
        "unverified_answer": "unverified",
    }
    for fixture_name, status in expected.items():
        assert main(["run-fixture", fixture_name]) == 0
        run_id = _run_id_from_output(capsys.readouterr().out)
        report_path = tmp_path / ".agenttrust" / "runs" / run_id / "groundguard-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == status


def test_run_live_uses_live_adapter_source(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    assert main(["run-live", "fake_tool_request"]) == 0

    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    intent = next(event for event in events if event["event_type"] == "tool_intent")
    assert intent["source"] == "live_adapter"
    assert intent["tool_name"] == "read_file"


def test_policy_validate_loads_policy(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    capsys.readouterr()

    assert main(["policy", "validate", ".agenttrust/policy.yaml"]) == 0

    assert "valid policy file" in capsys.readouterr().out
