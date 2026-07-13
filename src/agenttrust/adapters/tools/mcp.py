"""MCP Lite wrapper tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agenttrust.adapters.mcp.runtime import invoke_trusted_mcp_tool
from agenttrust.domain.models import ToolIntent, ToolResult
from agenttrust.mcp_lite import (
    has_mcp_consent,
    is_mcp_tool_trusted,
    mcp_sandbox_profile,
    mcp_trust_record,
    resolve_mcp_server,
)


def mcp_tool(intent: ToolIntent, project_root: Path) -> ToolResult:
    server = intent.arguments.get("server", "unknown")
    tool = intent.arguments.get("tool", "unknown")
    server_name = str(server)
    tool_name = str(tool)
    config = resolve_mcp_server(project_root, server_name)
    explicitly_simulated = intent.arguments.get("simulated") is True
    simulation_allowed = intent.runtime_mode == "test" or intent.simulation_allowed
    if explicitly_simulated and not simulation_allowed:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error="simulated MCP execution is only available in test mode or when explicitly enabled by the runtime",
            metadata={"mcp_server_name": server_name, "simulation_denied": True},
        )
    if config is None and intent.runtime_mode != "test" and not explicitly_simulated:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error=f"MCP server configuration was not found: {server_name}",
            metadata={"mcp_server_name": server_name, "mcp_config_required": True},
        )
    if intent.runtime_mode != "test" and not explicitly_simulated and not is_mcp_tool_trusted(project_root, str(server), str(tool)):
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error=f"MCP tool '{tool}' on server '{server}' is not trusted",
            metadata={"mcp_server_name": str(server), "trust_required": True},
        )
    if intent.runtime_mode != "test" and not explicitly_simulated and not has_mcp_consent(project_root, str(server)):
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error=f"MCP server '{server}' requires explicit consent",
            metadata={"mcp_server_name": str(server), "consent_required": True},
        )
    if config is not None and mcp_trust_record(project_root, server_name) is not None and not explicitly_simulated:
        trust_record = mcp_trust_record(project_root, server_name)
        if trust_record is None:
            return ToolResult(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                status="error",
                error=f"MCP server '{server_name}' has no trusted tool fingerprint",
                metadata={"mcp_server_name": server_name, "trust_required": True},
            )
        raw_input = intent.arguments.get("input", {})
        if not isinstance(raw_input, dict):
            return ToolResult(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                status="error",
                error="MCP tool input must be an object",
                metadata={"mcp_server_name": server_name, "mcp_tool_name": tool_name},
            )
        invocation = invoke_trusted_mcp_tool(project_root, config, trust_record, tool_name, raw_input)
        metadata = {
            "mcp_server_name": server_name,
            "mcp_tool_name": tool_name,
            "mcp_sandbox_profile": mcp_sandbox_profile(project_root, server_name),
            "mcp_config_source": str(config.config_path),
            **(invocation.metadata or {}),
        }
        if invocation.status != "ok":
            return ToolResult(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                status="error",
                error=invocation.error,
                metadata=metadata,
            )
        digest = "sha256:" + hashlib.sha256(invocation.output_preview.encode("utf-8")).hexdigest()
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="ok",
            output_preview=invocation.output_preview,
            output_digest=digest,
            metadata=metadata,
        )
    if config is not None and not explicitly_simulated:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error=f"MCP server '{server_name}' has no trusted tool fingerprint",
            metadata={"mcp_server_name": server_name, "trust_required": True},
        )
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
            "mcp_execution_mode": "simulated",
            "mcp_simulation_explicit": explicitly_simulated,
            "simulated": True,
            "mcp_sandbox_profile": mcp_sandbox_profile(project_root, str(server)) if intent.runtime_mode != "test" else "test",
        },
    )
