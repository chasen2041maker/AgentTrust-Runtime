"""YAML policy loading and rule matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from agenttrust.permissions.hooks import HookRule
from agenttrust.schemas import ToolIntent


VALID_EFFECTS = {"allow", "ask", "deny"}


@dataclass(frozen=True)
class PolicyRule:
    id: str
    tool: str
    effect: str
    reason: str
    paths: tuple[str, ...] = ()
    command_patterns: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PolicyRule":
        effect = str(raw.get("effect", "deny"))
        if effect not in VALID_EFFECTS:
            raise ValueError(f"invalid policy effect: {effect}")
        return cls(
            id=str(raw.get("id", "unnamed-rule")),
            tool=str(raw["tool"]),
            effect=effect,
            reason=str(raw.get("reason", "")),
            paths=tuple(str(path) for path in raw.get("paths", ()) or ()),
            command_patterns=tuple(str(pattern) for pattern in raw.get("command_patterns", ()) or ()),
        )

    def matches(self, intent: ToolIntent) -> bool:
        if self.tool != intent.tool_name:
            return False
        if self.paths:
            path_value = intent.arguments.get("path")
            if not isinstance(path_value, str):
                return False
            normalized = path_value.replace("\\", "/")
            return any(fnmatch(normalized, pattern.replace("\\", "/")) for pattern in self.paths)
        if self.command_patterns:
            command = intent.arguments.get("command")
            if not isinstance(command, str):
                return False
            return any(fnmatch(command, pattern) or pattern in command for pattern in self.command_patterns)
        return True


@dataclass(frozen=True)
class Policy:
    project_root: str = "."
    mode: str = "default"
    rules: tuple[PolicyRule, ...] = field(default_factory=tuple)
    hooks: tuple[HookRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Policy":
        return cls(
            project_root=str(raw.get("project_root", ".")),
            mode=str(raw.get("mode", "default")),
            rules=tuple(PolicyRule.from_dict(rule) for rule in raw.get("rules", ()) or ()),
            hooks=tuple(
                HookRule.from_dict(hook)
                for hook in ((raw.get("hooks", {}) or {}).get("pre_tool", ()) or ())
            ),
        )


DEFAULT_POLICY_TEXT = """project_root: .
mode: default

rules:
  - id: block-secret-files
    tool: read_file
    paths:
      - "**/.env"
      - ".env"
      - "**/*.pem"
      - "~/.ssh/**"
    effect: deny
    reason: "secret files are blocked"

  - id: deny-dangerous-shell
    tool: shell
    command_patterns:
      - "rm -rf /"
      - "mkfs"
      - "curl * | sh"
      - "wget * | sh"
    effect: deny
    reason: "dangerous shell command"

  - id: ask-before-write-code
    tool: write_file
    paths:
      - "src/**"
      - "tests/**"
    effect: ask
    reason: "code changes require approval"

  - id: ask-before-mcp-tool
    tool: mcp_tool
    effect: ask
    reason: "MCP tool calls require approval"
"""


def load_policy(path: Path) -> Policy:
    if not path.exists():
        return Policy.from_dict(yaml.safe_load(DEFAULT_POLICY_TEXT))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("policy file must contain a mapping")
    return Policy.from_dict(raw)
