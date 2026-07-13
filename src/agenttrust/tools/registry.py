"""Static tool registry for built-in and Lite tools."""

from __future__ import annotations

from dataclasses import dataclass


TOOL_SPEC_SCHEMA_VERSION = "agenttrust.tool-spec/v1"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    input_schema: dict[str, object]
    default_effect: str
    enabled: bool = True
    source: str = "builtin"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": TOOL_SPEC_SCHEMA_VERSION,
            "name": self.name,
            "category": self.category,
            "input_schema": self.input_schema,
            "default_effect": self.default_effect,
            "enabled": self.enabled,
            "source": self.source,
        }


TOOL_SPECS: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        name="read_file",
        category="file",
        input_schema={"path": "string"},
        default_effect="allow",
    ),
    "write_file": ToolSpec(
        name="write_file",
        category="file",
        input_schema={"path": "string", "content": "string"},
        default_effect="ask",
    ),
    "shell": ToolSpec(
        name="shell",
        category="process",
        input_schema={"argv": "string[]", "simulated_output": "string?"},
        default_effect="ask",
    ),
    "unsafe_shell_command": ToolSpec(
        name="unsafe_shell_command",
        category="process",
        input_schema={"command": "string"},
        default_effect="deny",
        source="explicit_compatibility",
    ),
    "git_diff": ToolSpec(
        name="git_diff",
        category="git",
        input_schema={},
        default_effect="allow",
    ),
    "mcp_tool": ToolSpec(
        name="mcp_tool",
        category="mcp",
        input_schema={"server": "string", "tool": "string", "input": "object", "simulated": "boolean?"},
        default_effect="ask",
        source="mcp_lite",
    ),
    "skill_context": ToolSpec(
        name="skill_context",
        category="skill",
        input_schema={"skill": "string"},
        default_effect="allow",
        source="skill_context",
    ),
}


def list_tool_specs() -> list[ToolSpec]:
    return [TOOL_SPECS[name] for name in sorted(TOOL_SPECS)]


def get_tool_spec(name: str) -> ToolSpec:
    try:
        return TOOL_SPECS[name]
    except KeyError as exc:
        available = ", ".join(sorted(TOOL_SPECS))
        raise ValueError(f"unknown tool '{name}'. Available tools: {available}") from exc
