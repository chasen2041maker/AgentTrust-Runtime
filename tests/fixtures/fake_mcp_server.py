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
                    }
                ]
            },
        )
    elif method == "tools/call":
        params = request.get("params", {})
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        respond(request_id, {"content": [{"type": "text", "text": json.dumps(arguments, sort_keys=True)}]})
