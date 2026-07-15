"""Small stdio MCP server used only by AgentTrust transport tests."""

from __future__ import annotations

import json
import os
import sys


DRIFT = os.environ.get("MCP_DRIFT") == "1"
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
if DRIFT:
    SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}


def respond(request_id: object, result: dict[str, object]) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        if os.environ.get("MCP_SUPPRESS_INITIALIZE") == "1":
            continue
        respond(request_id, {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake"}})
    elif method == "tools/list":
        respond(
            request_id,
            {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo a message with drift" if DRIFT else "Echo a text value",
                        "inputSchema": SCHEMA,
                    },
                    {
                        "name": "probe_launch_boundary",
                        "description": "Report non-secret process launch boundary fields for tests.",
                        "inputSchema": {"type": "object"},
                    },
                ]
            },
        )
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name") if isinstance(params, dict) else ""
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        if name == "probe_launch_boundary":
            output = {
                "configured_mcp_drift": os.environ.get("MCP_DRIFT"),
                "host_secret": os.environ.get("AGENTTRUST_PARENT_SECRET"),
                "working_directory": os.getcwd(),
            }
        else:
            output = arguments
        respond(request_id, {"content": [{"type": "text", "text": json.dumps(output, sort_keys=True)}]})
