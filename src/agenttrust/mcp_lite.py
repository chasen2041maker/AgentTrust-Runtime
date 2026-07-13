"""MCP Lite config inspection."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from agenttrust.adapters.mcp.stdio import McpServerConfig, McpToolDescriptor


def grant_mcp_consent(project_root: Path, server_name: str, actor_id: str = "local-user") -> Path:
    """Persist explicit consent for a local MCP server."""
    path = project_root / ".agenttrust" / "mcp-consent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _consent_records(path)
    records[server_name] = {"actor_id": actor_id}
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def revoke_mcp_consent(project_root: Path, server_name: str) -> Path:
    """Revoke a previously persisted MCP server consent record."""

    path = project_root / ".agenttrust" / "mcp-consent.json"
    records = _consent_records(path)
    records.pop(server_name, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def has_mcp_consent(project_root: Path, server_name: str) -> bool:
    return server_name in _consent_records(project_root / ".agenttrust" / "mcp-consent.json")


def trust_mcp_server(
    project_root: Path, server_name: str, allowed_tools: list[str], sandbox_profile: str = "strict"
) -> Path:
    """Register a trusted local MCP server and its allowed tool surface."""
    path = project_root / ".agenttrust" / "mcp-trust.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _consent_records(path)
    records[server_name] = {"allowed_tools": sorted(set(allowed_tools)), "sandbox_profile": sandbox_profile}
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def trust_mcp_server_surface(
    project_root: Path,
    config: McpServerConfig,
    descriptors: list[McpToolDescriptor],
    allowed_tools: list[str],
    sandbox_profile: str = "strict",
) -> Path:
    """Persist tool-level trust fingerprints obtained from a live `tools/list` call."""

    descriptor_by_name = {descriptor.name: descriptor for descriptor in descriptors}
    missing = sorted(set(allowed_tools) - set(descriptor_by_name))
    if missing:
        raise ValueError(f"MCP tools not exposed by {config.name}: {', '.join(missing)}")
    path = project_root / ".agenttrust" / "mcp-trust.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _consent_records(path)
    records[config.name] = {
        "allowed_tools": sorted(set(allowed_tools)),
        "sandbox_profile": sandbox_profile,
        "trust_status": "trusted",
        "server_command_hash": mcp_server_command_hash(config),
        "tool_fingerprints": {
            name: _tool_fingerprint(descriptor_by_name[name]) for name in sorted(set(allowed_tools))
        },
    }
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def is_mcp_tool_trusted(project_root: Path, server_name: str, tool_name: str) -> bool:
    record = _consent_records(project_root / ".agenttrust" / "mcp-trust.json").get(server_name)
    return (
        isinstance(record, dict)
        and record.get("trust_status", "trusted") == "trusted"
        and tool_name in record.get("allowed_tools", [])
    )


def mcp_sandbox_profile(project_root: Path, server_name: str) -> str | None:
    record = _consent_records(project_root / ".agenttrust" / "mcp-trust.json").get(server_name)
    profile = record.get("sandbox_profile") if isinstance(record, dict) else None
    return str(profile) if profile else None


def mcp_trust_record(project_root: Path, server_name: str) -> dict[str, object] | None:
    record = _consent_records(project_root / ".agenttrust" / "mcp-trust.json").get(server_name)
    return dict(record) if isinstance(record, dict) else None


def mark_mcp_trust_stale(project_root: Path, server_name: str, reason: str) -> Path:
    """Invalidate a trusted surface after command or schema drift is detected."""

    path = project_root / ".agenttrust" / "mcp-trust.json"
    records = _consent_records(path)
    record = records.get(server_name)
    if not isinstance(record, dict):
        raise ValueError(f"MCP server is not trusted: {server_name}")
    record["trust_status"] = "trust_stale"
    record["stale_reason"] = reason
    records[server_name] = record
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_mcp_servers(path: Path) -> dict[str, McpServerConfig]:
    """Load launchable MCP stdio entries without starting any server."""

    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    servers = raw.get("mcpServers", raw.get("servers", raw))
    if not isinstance(servers, dict):
        raise ValueError("MCP config must contain a mapping of servers")
    result: dict[str, McpServerConfig] = {}
    for name, raw_server in servers.items():
        if not isinstance(raw_server, dict):
            continue
        command = raw_server.get("command")
        args = raw_server.get("args", [])
        env = raw_server.get("env", {})
        if not isinstance(command, str) or not command:
            continue
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError(f"MCP server {name} requires string args")
        if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
            raise ValueError(f"MCP server {name} requires string env entries")
        result[str(name)] = McpServerConfig(
            name=str(name),
            command=command,
            args=tuple(args),
            env=dict(env),
            config_path=path,
        )
    return result


def resolve_mcp_server(project_root: Path, server_name: str) -> McpServerConfig | None:
    """Resolve a named project-local server configuration without launching it."""

    for path in (project_root / ".mcp.json", project_root / ".agenttrust" / "mcp.json"):
        if not path.exists():
            continue
        config = load_mcp_servers(path).get(server_name)
        if config is not None:
            return config
    return None


def mcp_server_command_hash(config: McpServerConfig) -> str:
    return _schema_hash({"command": config.command, "args": list(config.args)})


def mcp_tool_fingerprint(descriptor: McpToolDescriptor) -> dict[str, str]:
    return _tool_fingerprint(descriptor)


def _consent_records(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


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
                "config_source": str(path),
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


def _tool_fingerprint(descriptor: McpToolDescriptor) -> dict[str, str]:
    return {
        "description_hash": _schema_hash(descriptor.description),
        "input_schema_hash": _schema_hash(descriptor.input_schema),
    }


def _risk_level(server: dict[str, Any]) -> str:
    command = str(server.get("command", "")).lower()
    if any(token in command for token in ("powershell", "bash", "sh", "cmd")):
        return "high"
    return "medium" if server.get("env") else "low"
