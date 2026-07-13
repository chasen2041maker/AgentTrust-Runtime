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
    snapshot = next(event for event in events if event["event_type"] == "policy_snapshot")
    assert str(snapshot["policy_version"]).startswith("sha256:")
    assert (tmp_path / ".agenttrust" / "runs" / run_id / "policy-snapshot.yaml").exists()
    assert all(event["actor_id"] == "local-user" for event in events)
    assert all(str(event["policy_version"]).startswith("sha256:") for event in events)
    assert next(event for event in events if event["event_type"] == "tool_intent")["tool_name"] == "shell"
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


def test_evidence_verify_accepts_an_untampered_run(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["run-fixture", "verified_answer"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)

    assert main(["evidence", "verify", run_id]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    assert main(["evidence", "export", run_id]) == 0
    export_path = Path(capsys.readouterr().out.strip())
    assert export_path.exists()
    assert json.loads(export_path.read_text(encoding="utf-8").splitlines()[0])["resource"] == "agenttrust.runtime"


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

    assert main(["policy", "validate", "missing-policy.yaml"]) == 2
    assert "policy file not found" in capsys.readouterr().err


def test_tool_registry_cli_lists_and_inspects_lite_tools(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["tools", "list"]) == 0
    output = capsys.readouterr().out
    assert "mcp_tool\tmcp\tmcp_lite\task" in output
    assert "skill_context\tskill\tskill_context\tallow" in output

    assert main(["tools", "inspect", "mcp_tool"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "mcp_tool"
    assert payload["default_effect"] == "ask"
    assert payload["source"] == "mcp_lite"

    assert main(["tools", "inspect", "missing_tool"]) == 2
    assert "unknown tool" in capsys.readouterr().err


def test_mcp_inspect_redacts_env_values_and_hashes_tool_schema(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local-files": {
                        "command": "powershell",
                        "args": ["-NoProfile"],
                        "env": {"API_TOKEN": "secret-token"},
                        "tools": {"read_project_file": {"inputSchema": {"path": "string"}}},
                    }
                }
            }
        ),
        encoding="utf-8-sig",
    )

    assert main(["mcp", "inspect", ".mcp.json"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    server = payload["servers"][0]
    assert server["name"] == "local-files"
    assert server["env_keys"] == ["API_TOKEN"]
    assert "secret-token" not in output
    assert server["risk"] == "high"
    assert server["tool_names"] == ["read_project_file"]
    assert server["tool_schemas"][0]["schema_hash"].startswith("sha256:")

    (tmp_path / "bad.mcp.json").write_text("{bad json", encoding="utf-8")
    assert main(["mcp", "inspect", "bad.mcp.json"]) == 2
    assert "invalid MCP config" in capsys.readouterr().err


def test_skill_cli_and_run_with_skill_records_policy_and_fact_check(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    capsys.readouterr()

    assert main(["skills", "list"]) == 0
    assert "code-review" in capsys.readouterr().out

    assert main(["skills", "inspect", "code-review"]) == 0
    skill_payload = json.loads(capsys.readouterr().out)
    assert skill_payload["allowed_tools"] == ["read_file", "git_diff"]
    assert skill_payload["blocked_tools"] == ["shell", "write_file"]

    assert main(["run", "--skill", "code-review", "review this repository"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    assert any(event["event_type"] == "skill_loaded" for event in events)
    assert any(event["event_type"] == "skill_decision" and event["effect"] == "allow" for event in events)
    intent = next(event for event in events if event["event_type"] == "tool_intent")
    assert intent["source"] == "skill_lite"
    assert intent["tool_name"] == "git_diff"
    report = json.loads((tmp_path / ".agenttrust" / "runs" / run_id / "groundguard-report.json").read_text())
    assert report["status"] == "verified"


def test_skill_blocked_tool_denies_before_permission_and_execution(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["run-fixture", "skill_blocked_tool", "--mode", "test"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    skill_decision = next(event for event in events if event["event_type"] == "skill_decision")
    decisions = json.loads((tmp_path / ".agenttrust" / "runs" / run_id / "decisions.json").read_text(encoding="utf-8"))
    assert skill_decision["effect"] == "deny"
    assert skill_decision["reason"] == "tool blocked by skill policy"
    assert any(decision.get("effect") == "deny" and decision.get("skill_name") == "code-review" for decision in decisions)
    assert not any(event["event_type"] == "permission_decision" for event in events)
    assert not any(event["event_type"] == "tool_result" for event in events)


def test_mcp_fixtures_cover_default_deny_and_test_approval(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["run-fixture", "mcp_tool_denied", "--non-interactive"]) == 0
    denied_run_id = _run_id_from_output(capsys.readouterr().out)
    denied_events = _events_for_run(tmp_path, denied_run_id)
    denied_permission = next(event for event in denied_events if event["event_type"] == "permission_decision")
    assert denied_permission["effect"] == "ask"
    assert denied_permission["final_effect"] == "deny"
    assert not any(event["event_type"] == "tool_result" for event in denied_events)

    assert main(["run-fixture", "mcp_tool_approved", "--mode", "test"]) == 0
    approved_run_id = _run_id_from_output(capsys.readouterr().out)
    approved_events = _events_for_run(tmp_path, approved_run_id)
    approved_permission = next(event for event in approved_events if event["event_type"] == "permission_decision")
    assert approved_permission["effect"] == "ask"
    assert approved_permission["final_effect"] == "allow"
    tool_result = next(event for event in approved_events if event["event_type"] == "tool_result")
    assert tool_result["metadata"]["mcp_server_name"] == "local-files"
    assert tool_result["metadata"]["mcp_tool_schema_hash"].startswith("sha256:")
    report = json.loads((tmp_path / ".agenttrust" / "runs" / approved_run_id / "groundguard-report.json").read_text())
    assert report["status"] == "verified"


def test_hook_fixture_denies_before_sandbox_and_tool_execution(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()

    assert main(["run-fixture", "blocked_by_hook", "--mode", "test"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    hook = next(event for event in events if event["event_type"] == "hook_decision")
    permission = next(event for event in events if event["event_type"] == "permission_decision")
    assert hook["hook_id"] == "block-src-write"
    assert permission["final_effect"] == "deny"
    assert permission["reason"] == "src writes blocked by hook"
    decisions = json.loads((tmp_path / ".agenttrust" / "runs" / run_id / "decisions.json").read_text(encoding="utf-8"))
    assert any(decision.get("hook_id") == "block-src-write" for decision in decisions)
    assert not any(event["event_type"] == "sandbox_decision" for event in events)
    assert not (tmp_path / "src" / "app.py").exists()


def test_write_and_restore_fixture_records_backup_and_restore_trace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "tmp" / "demo.txt"
    target.parent.mkdir()
    target.write_text("original", encoding="utf-8")

    assert main(["run-fixture", "write_and_restore", "--mode", "test"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)
    assert target.read_text(encoding="utf-8") == "changed by agent"
    events = _events_for_run(tmp_path, run_id)
    assert any(event["event_type"] == "backup_created" for event in events)

    assert main(["restore", run_id, "--dry-run"]) == 0
    dry_run_actions = json.loads(capsys.readouterr().out)
    assert dry_run_actions[0]["action"] == "restore"
    assert target.read_text(encoding="utf-8") == "changed by agent"

    assert main(["restore", run_id]) == 0
    restore_actions = json.loads(capsys.readouterr().out)
    assert restore_actions[0]["action"] == "restore"
    assert target.read_text(encoding="utf-8") == "original"
    events_after_restore = _events_for_run(tmp_path, run_id)
    assert any(event["event_type"] == "restore_preview" for event in events_after_restore)
    assert any(event["event_type"] == "restore_applied" for event in events_after_restore)


def test_memory_and_context_cli_build_preview_and_export(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["memory", "add", "project", "GroundGuard verifies final numeric claims."]) == 0
    capsys.readouterr()
    assert main(["memory", "add", "decision", "Noninteractive ask is denied by default."]) == 0
    capsys.readouterr()

    assert main(["memory", "inspect"]) == 0
    memory = json.loads(capsys.readouterr().out)
    assert "GroundGuard verifies" in memory["project"]
    assert memory["decisions"][0]["text"] == "Noninteractive ask is denied by default."

    assert main(["context", "build", "--skill", "code-review", "--budget", "500"]) == 0
    context_paths = [Path(line) for line in capsys.readouterr().out.splitlines()]
    manifest = json.loads(context_paths[1].read_text(encoding="utf-8"))
    assert manifest["budget"] == 500
    assert manifest["included_skill"] == "code-review"
    assert manifest["policy_hash"].startswith("sha256:")
    assert "read_file" in manifest["included_tools"]

    assert main(["context", "preview", "--skill", "code-review", "--budget", "500"]) == 0
    assert "# AgentTrust Context Pack" in capsys.readouterr().out

    assert main(["context", "export", "--run", "run_context_test"]) == 0
    export_paths = [Path(line) for line in capsys.readouterr().out.splitlines()]
    assert all(path.exists() for path in export_paths)


def test_memory_context_pack_fixture_records_context_events(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["run-fixture", "memory_context_pack"]) == 0
    run_id = _run_id_from_output(capsys.readouterr().out)
    events = _events_for_run(tmp_path, run_id)
    assert any(event["event_type"] == "memory_loaded" for event in events)
    context_event = next(event for event in events if event["event_type"] == "context_pack_built")
    assert Path(str(context_event["run_context_pack"])).exists()
    assert Path(str(context_event["run_context_manifest"])).exists()
    assert (tmp_path / ".agenttrust" / "runs" / run_id / "context-pack.md").exists()
    assert (tmp_path / ".agenttrust" / "context" / "context-pack.md").exists()
