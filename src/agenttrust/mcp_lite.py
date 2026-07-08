"""MCP Lite config inspection."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


def inspect_mcp_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    servers = raw.get("mcpServers", raw.get("servers", raw))
    if not isinstance(servers, dict):
        raise ValueError("MCP config must contain a mapping of servers")
    inspected = []
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        env = server.get("env", {}) or {}
        tools = server.get("tools", []) or []
        inspected.append(
            {
                "name": str(name),
                "command": server.get("command"),
                "args": server.get("args", []),
                "env_keys": sorted(env) if isinstance(env, dict) else [],
                "tool_names": _tool_names(tools),
                "tool_schemas": _tool_schemas(tools),
                "risk": _risk_level(server),
            }
        )
    return {"servers": inspected}


def _tool_names(tools: object) -> list[str]:
    if isinstance(tools, dict):
        return sorted(str(name) for name in tools)
    if isinstance(tools, list):
        names = []
        for item in tools:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict) and "name" in item:
                names.append(str(item["name"]))
        return sorted(names)
    return []


def _tool_schemas(tools: object) -> list[dict[str, str]]:
    if isinstance(tools, dict):
        return [
            {"name": str(name), "schema_hash": _schema_hash(schema)}
            for name, schema in sorted(tools.items(), key=lambda item: str(item[0]))
        ]
    if isinstance(tools, list):
        schemas = []
        for item in tools:
            if isinstance(item, dict) and "name" in item:
                schemas.append({"name": str(item["name"]), "schema_hash": _schema_hash(item)})
            elif isinstance(item, str):
                schemas.append({"name": item, "schema_hash": _schema_hash({"name": item})})
        return sorted(schemas, key=lambda item: item["name"])
    return []


def _schema_hash(schema: object) -> str:
    raw = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _risk_level(server: dict[str, Any]) -> str:
    command = str(server.get("command", "")).lower()
    if any(token in command for token in ("powershell", "bash", "sh", "cmd")):
        return "high"
    return "medium" if server.get("env") else "low"
