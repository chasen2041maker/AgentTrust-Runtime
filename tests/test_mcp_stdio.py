"""Tests for trusted real MCP stdio transport and schema drift rejection."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from agenttrust.adapters.mcp.runtime import list_server_tools
from agenttrust.adapters.tools.gateway import ToolGateway
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


def test_schema_drift_marks_existing_mcp_trust_stale_and_blocks_call(tmp_path: Path) -> None:
    _write_server_config(tmp_path)
    _trust_fake_server(tmp_path)
    _write_server_config(tmp_path, drift=True)

    result = ToolGateway().execute(_intent(), tmp_path)

    assert result.status == "error"
    assert result.metadata["mcp_trust_status"] == "trust_stale"
    assert result.metadata["mcp_stale_reason"] == "tool_schema_changed"
    assert mcp_trust_record(tmp_path, "fake")["trust_status"] == "trust_stale"
