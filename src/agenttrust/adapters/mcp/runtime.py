"""Trusted execution of a real local MCP stdio tool call."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from agenttrust.adapters.mcp.stdio import McpServerConfig, McpStdioClient, McpToolDescriptor, McpTransportError, McpProtocolError
from agenttrust.mcp_lite import mark_mcp_trust_stale, mcp_server_command_hash, mcp_tool_fingerprint


@dataclass(frozen=True)
class McpInvocationResult:
    """A structured real-MCP invocation result for the ToolGateway adapter."""

    status: str
    output_preview: str = ""
    error: str | None = None
    metadata: dict[str, object] | None = None


def invoke_trusted_mcp_tool(
    project_root,
    config: McpServerConfig,
    trust_record: Mapping[str, object],
    tool_name: str,
    arguments: Mapping[str, object],
    timeout_seconds: float = 10.0,
) -> McpInvocationResult:
    """Verify trust fingerprints on reconnect before forwarding `tools/call`."""

    if trust_record.get("server_command_hash") != mcp_server_command_hash(config):
        mark_mcp_trust_stale(project_root, config.name, "server_command_changed")
        return McpInvocationResult(
            status="error",
            error="MCP server command changed since trust was granted",
            metadata={"mcp_trust_status": "trust_stale", "mcp_stale_reason": "server_command_changed"},
        )
    try:
        with McpStdioClient(config, timeout_seconds=timeout_seconds) as client:
            descriptors = client.list_tools()
            descriptor = next((item for item in descriptors if item.name == tool_name), None)
            if descriptor is None:
                mark_mcp_trust_stale(project_root, config.name, "trusted_tool_missing")
                return McpInvocationResult(
                    status="error",
                    error=f"MCP server no longer exposes trusted tool: {tool_name}",
                    metadata={"mcp_trust_status": "trust_stale", "mcp_stale_reason": "trusted_tool_missing"},
                )
            expected = _trusted_fingerprint(trust_record, tool_name)
            actual = mcp_tool_fingerprint(descriptor)
            if expected != actual:
                mark_mcp_trust_stale(project_root, config.name, "tool_schema_changed")
                return McpInvocationResult(
                    status="error",
                    error=f"MCP tool schema drift detected: {tool_name}",
                    metadata={
                        "mcp_trust_status": "trust_stale",
                        "mcp_stale_reason": "tool_schema_changed",
                        "mcp_tool_schema_hash": actual["input_schema_hash"],
                    },
                )
            response = client.call_tool(tool_name, arguments)
    except (McpTransportError, McpProtocolError) as exc:
        return McpInvocationResult(
            status="error",
            error=str(exc),
            metadata={"mcp_transport": "stdio", "mcp_error_type": type(exc).__name__},
        )

    return McpInvocationResult(
        status="ok",
        output_preview=_output_preview(response),
        metadata={
            "mcp_transport": "stdio",
            "mcp_tool_schema_hash": actual["input_schema_hash"],
            "mcp_tool_description_hash": actual["description_hash"],
            "mcp_server_command_hash": mcp_server_command_hash(config),
            "mcp_response": response,
        },
    )


def list_server_tools(config: McpServerConfig, timeout_seconds: float = 10.0) -> list[McpToolDescriptor]:
    """Launch an explicitly permitted server and query its declared tool surface."""

    with McpStdioClient(config, timeout_seconds=timeout_seconds) as client:
        return client.list_tools()


def _trusted_fingerprint(trust_record: Mapping[str, object], tool_name: str) -> dict[str, str] | None:
    raw_tools = trust_record.get("tool_fingerprints")
    if not isinstance(raw_tools, dict):
        return None
    raw = raw_tools.get(tool_name)
    if not isinstance(raw, dict):
        return None
    description_hash = raw.get("description_hash")
    input_schema_hash = raw.get("input_schema_hash")
    if not isinstance(description_hash, str) or not isinstance(input_schema_hash, str):
        return None
    return {"description_hash": description_hash, "input_schema_hash": input_schema_hash}


def _output_preview(response: Mapping[str, object]) -> str:
    content = response.get("content")
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)[:500]
    return json.dumps(dict(response), ensure_ascii=False, sort_keys=True)[:500]
