"""Tests for trusted real MCP stdio transport and schema drift rejection."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from agenttrust.adapters.mcp.runtime import list_server_tools
from agenttrust.adapters.tools.gateway import ToolGateway
from agenttrust import AgentTrustRuntime
from agenttrust.cli import main
from agenttrust.domain.models import ToolIntent
from agenttrust.mcp_lite import grant_mcp_consent, load_mcp_servers, mcp_trust_record, trust_mcp_server_surface


def _write_server_config(project_root: Path, drift: bool = False) -> None:
    (project_root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fake": {
                        "command": sys.executable,
                        "args": [str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")],
                        "env": {"MCP_DRIFT": "1" if drift else "0"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _trust_fake_server(project_root: Path) -> None:
    config = load_mcp_servers(project_root / ".mcp.json")["fake"]
    grant_mcp_consent(project_root, "fake")
    trust_mcp_server_surface(project_root, config, list_server_tools(config), ["echo"])


def _intent() -> ToolIntent:
    return ToolIntent(
        run_id="run_mcp",
        tool_call_id="call_001",
        tool_name="mcp_tool",
        arguments={"server": "fake", "tool": "echo", "input": {"text": "hello"}},
        source="test",
        runtime_mode="interactive",
    )


def test_real_mcp_stdio_call_requires_trusted_surface_and_returns_structured_result(tmp_path: Path) -> None:
    _write_server_config(tmp_path)
    _trust_fake_server(tmp_path)

    result = ToolGateway().execute(_intent(), tmp_path)

    assert result.status == "ok"
    assert result.output_preview == '{"text": "hello"}'
    assert result.metadata["mcp_transport"] == "stdio"
    assert result.metadata["mcp_tool_name"] == "echo"
    assert result.metadata["mcp_tool_schema_hash"].startswith("sha256:")


def test_mcp_without_configuration_returns_an_error_outside_test_mode(tmp_path: Path) -> None:
    intent = ToolIntent(
        run_id="run_mcp",
        tool_call_id="call_001",
        tool_name="mcp_tool",
        arguments={"server": "missing", "tool": "echo", "input": {}},
        source="test",
        runtime_mode="noninteractive",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "error"
    assert result.metadata["mcp_config_required"] is True
    assert "configuration was not found" in (result.error or "")


def test_explicitly_simulated_mcp_call_is_marked_in_evidence_metadata(tmp_path: Path) -> None:
    intent = ToolIntent(
        run_id="run_mcp",
        tool_call_id="call_001",
        tool_name="mcp_tool",
        arguments={"server": "simulated", "tool": "echo", "input": {}, "simulated": True},
        source="test",
        runtime_mode="interactive",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "ok"
    assert result.metadata["mcp_execution_mode"] == "simulated"
    assert result.metadata["mcp_simulation_explicit"] is True


def test_schema_drift_marks_existing_mcp_trust_stale_and_blocks_call(tmp_path: Path) -> None:
    _write_server_config(tmp_path)
    _trust_fake_server(tmp_path)
    _write_server_config(tmp_path, drift=True)

    result = ToolGateway().execute(_intent(), tmp_path)

    assert result.status == "error"
    assert result.metadata["mcp_trust_status"] == "trust_stale"
    assert result.metadata["mcp_stale_reason"] == "tool_schema_changed"
    assert mcp_trust_record(tmp_path, "fake")["trust_status"] == "trust_stale"


def test_mcp_cli_discovers_inspects_consents_and_trusts_a_real_stdio_server(tmp_path: Path, capsys) -> None:
    _write_server_config(tmp_path)

    assert main(["--project-root", str(tmp_path), "mcp", "discover"]) == 0
    discovered = json.loads(capsys.readouterr().out)
    assert any(server["name"] == "fake" for server in discovered["servers"])

    assert main(["--project-root", str(tmp_path), "mcp", "inspect", "fake"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["servers"][0]["name"] == "fake"
    assert inspected["servers"][0]["env_keys"] == ["MCP_DRIFT"]

    assert main(["--project-root", str(tmp_path), "mcp", "trust", "fake", "--tool", "echo"]) == 2
    assert "requires explicit consent" in capsys.readouterr().err

    assert main(["--project-root", str(tmp_path), "mcp", "consent", "grant", "fake"]) == 0
    capsys.readouterr()
    assert main(["--project-root", str(tmp_path), "mcp", "trust", "fake", "--tool", "echo"]) == 0
    capsys.readouterr()
    assert mcp_trust_record(tmp_path, "fake")["tool_fingerprints"]["echo"]["input_schema_hash"].startswith("sha256:")

    assert main(["--project-root", str(tmp_path), "mcp", "consent", "revoke", "fake"]) == 0


def test_real_mcp_call_is_recorded_in_a_governed_session_evidence_chain(tmp_path: Path) -> None:
    _write_server_config(tmp_path)
    _trust_fake_server(tmp_path)
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice") as session:
        result = session.execute("mcp_tool", {"server": "fake", "tool": "echo", "input": {"text": "trace"}})

    assert result.outcome.result is not None
    assert result.outcome.result.metadata["mcp_transport"] == "stdio"
    events = [json.loads(line) for line in (session.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    tool_result = next(event for event in events if event["event_type"] == "tool_result")
    assert tool_result["metadata"]["mcp_transport"] == "stdio"
