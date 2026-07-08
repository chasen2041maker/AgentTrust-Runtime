from __future__ import annotations

import json
from pathlib import Path

from agenttrust.cli import main


def _run_id_from_output(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("run_id="):
            return line.split("=", 1)[1]
    raise AssertionError(f"run_id not found in output: {output}")


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
    trace_path = tmp_path / ".agenttrust" / "runs" / run_id / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert [event["event_type"] for event in events] == [
        "run_started",
        "tool_intent",
        "tool_result",
        "final_answer",
        "run_completed",
    ]
    assert events[1]["tool_name"] == "read_file"
    assert events[2]["status"] == "ok"


def test_replay_prints_timeline(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    assert main(["run-fixture", "verified_answer"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)

    exit_code = main(["replay", run_id])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "run_started" in output
    assert "tool_result: read_file -> ok" in output


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
