from __future__ import annotations

from pathlib import Path
import sys

from agenttrust.runtime.gateway import ToolGateway
from agenttrust.schemas import ToolIntent


def test_gateway_executes_read_file(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    intent = ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="read_file",
        arguments={"path": "README.md"},
        source="test",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "ok"
    assert result.output_preview == "hello\n"
    assert result.metadata["lines"] == 1


def test_gateway_returns_error_for_unknown_tool(tmp_path: Path) -> None:
    intent = ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="unknown_tool",
        arguments={"path": "x.txt", "content": "hello"},
        source="test",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "error"
    assert result.error == "unknown tool: unknown_tool"
    assert result.metadata["available_tools"] == list(ToolGateway().tool_names)


def test_mcp_tool_requires_configuration_outside_test_mode(tmp_path: Path) -> None:
    intent = ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="mcp_tool",
        arguments={"server": "local-files", "tool": "read_project_file"},
        source="test",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "error"
    assert result.metadata["mcp_config_required"] is True


def test_shell_accepts_argv_without_invoking_a_command_shell(tmp_path: Path) -> None:
    intent = ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="shell",
        arguments={"argv": [sys.executable, "-c", "print('safe')"]},
        source="test",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "ok"
    assert result.output_preview.strip() == "safe"


def test_shell_rejects_legacy_command_strings(tmp_path: Path) -> None:
    intent = ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="shell",
        arguments={"command": "echo unsafe"},
        source="test",
    )

    result = ToolGateway().execute(intent, tmp_path)

    assert result.status == "error"
    assert result.error == "shell requires a non-empty argv list of strings"
