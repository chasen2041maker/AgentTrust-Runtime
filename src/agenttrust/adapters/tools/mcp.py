"""MCP Lite wrapper tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agenttrust.domain.models import ToolIntent, ToolResult


def mcp_tool(intent: ToolIntent, project_root: Path) -> ToolResult:
    server = intent.arguments.get("server", "unknown")
    tool = intent.arguments.get("tool", "unknown")
    payload = {
        "server": server,
        "tool": tool,
        "input": intent.arguments.get("input", {}),
    }
    output = intent.arguments.get("simulated_output")
    if not isinstance(output, str):
        output = (
            "AGENTTRUST_FACTS:\n"
            "mcp_tool_calls=1 count\n"
            "END_AGENTTRUST_FACTS\n"
        )
    digest = "sha256:" + hashlib.sha256(output.encode("utf-8")).hexdigest()
    return ToolResult(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        status="ok",
        output_preview=output[:500],
        output_digest=digest,
        metadata={
            "mcp_server_name": str(server),
            "mcp_tool_name": str(tool),
            "mcp_tool_schema_hash": "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "mcp_risk_level": "medium",
        },
    )
