"""Pure policy and hook rules for governed tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from agenttrust.domain.models import ToolIntent


VALID_EFFECTS = frozenset({"allow", "ask", "deny"})
VALID_FINAL_ANSWER_MODES = frozenset({"warn", "deny_completion", "require_revision"})


@dataclass(frozen=True)
class PolicyRule:
    """A policy rule matched against a normalized tool intent."""

    id: str
    tool: str
    effect: str
    reason: str
    paths: tuple[str, ...] = ()
    command_patterns: tuple[str, ...] = ()
    argv_patterns: tuple[tuple[str, ...], ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PolicyRule":
        effect = str(raw.get("effect", "deny"))
        if effect not in VALID_EFFECTS:
            raise ValueError(f"invalid policy effect: {effect}")
        raw_argv_patterns = raw.get("argv_patterns", ()) or ()
        if not isinstance(raw_argv_patterns, (list, tuple)):
            raise ValueError("argv_patterns must be a list of token lists")
        argv_patterns: list[tuple[str, ...]] = []
        for pattern in raw_argv_patterns:
            if not isinstance(pattern, (list, tuple)) or not pattern:
                raise ValueError("each argv pattern must be a non-empty token list")
            if not all(isinstance(token, str) and token for token in pattern):
                raise ValueError("argv pattern tokens must be non-empty strings")
            argv_patterns.append(tuple(pattern))
        return cls(
            id=str(raw.get("id", "unnamed-rule")),
            tool=str(raw["tool"]),
            effect=effect,
            reason=str(raw.get("reason", "")),
            paths=tuple(str(path) for path in raw.get("paths", ()) or ()),
            command_patterns=tuple(str(pattern) for pattern in raw.get("command_patterns", ()) or ()),
            argv_patterns=tuple(argv_patterns),
        )

    def matches(self, intent: ToolIntent) -> bool:
        if self.tool != intent.tool_name:
            return False
        if self.paths:
            path_value = intent.arguments.get("path")
            if not isinstance(path_value, str):
                return False
            normalized = path_value.replace("\\", "/")
            if not any(fnmatch(normalized, pattern.replace("\\", "/")) for pattern in self.paths):
                return False
        if self.command_patterns:
            command = intent.arguments.get("command")
            if not isinstance(command, str):
                return False
            if not any(fnmatch(command, pattern) or pattern in command for pattern in self.command_patterns):
                return False
        if self.argv_patterns:
            argv = _normalized_argv(intent.arguments.get("argv"))
            if argv is None:
                return False
            if not any(_argv_pattern_matches(argv, pattern) for pattern in self.argv_patterns):
                return False
        return True


def _normalized_argv(raw_argv: object) -> tuple[str, ...] | None:
    if not isinstance(raw_argv, list) or not raw_argv:
        return None
    if not all(isinstance(token, str) and token for token in raw_argv):
        return None
    return tuple(raw_argv)


def _argv_pattern_matches(argv: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    """Match normalized argv tokens; a final ** permits extra trailing tokens."""

    prefix = pattern[:-1] if pattern[-1] == "**" else pattern
    if len(argv) < len(prefix) or (len(argv) != len(prefix) and pattern[-1] != "**"):
        return False
    return all(fnmatch(token, token_pattern) for token, token_pattern in zip(argv, prefix))


@dataclass(frozen=True)
class HookRule:
    """A pre-tool control evaluated before permission finalization."""

    id: str
    tool: str
    action: str
    reason: str
    path_glob: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HookRule":
        when = raw.get("when", {}) or {}
        if not isinstance(when, dict):
            when = {}
        path_glob = raw.get("path_glob", when.get("path_glob"))
        return cls(
            id=str(raw.get("id", "unnamed-hook")),
            tool=str(raw.get("tool", when.get("tool", "*"))),
            action=str(raw.get("action", "deny")),
            reason=str(raw.get("reason", "blocked by hook")),
            path_glob=str(path_glob) if path_glob is not None else None,
        )

    def matches(self, intent: ToolIntent) -> bool:
        if self.tool not in {"*", intent.tool_name}:
            return False
        if self.path_glob:
            path = intent.arguments.get("path")
            if not isinstance(path, str):
                return False
            return fnmatch(path.replace("\\", "/"), self.path_glob.replace("\\", "/"))
        return True


@dataclass(frozen=True)
class Policy:
    """A framework-free collection of policy and hook rules."""

    project_root: str = "."
    mode: str = "default"
    rules: tuple[PolicyRule, ...] = field(default_factory=tuple)
    hooks: tuple[HookRule, ...] = field(default_factory=tuple)
    final_answer_mode: str = "warn"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Policy":
        final_answer = raw.get("final_answer", {}) or {}
        if not isinstance(final_answer, dict):
            raise ValueError("final_answer policy must contain a mapping")
        final_answer_mode = str(final_answer.get("on_incomplete", "warn"))
        if final_answer_mode not in VALID_FINAL_ANSWER_MODES:
            raise ValueError(f"invalid final_answer on_incomplete mode: {final_answer_mode}")
        return cls(
            project_root=str(raw.get("project_root", ".")),
            mode=str(raw.get("mode", "default")),
            rules=tuple(PolicyRule.from_dict(rule) for rule in raw.get("rules", ()) or ()),
            hooks=tuple(
                HookRule.from_dict(hook)
                for hook in ((raw.get("hooks", {}) or {}).get("pre_tool", ()) or ())
            ),
            final_answer_mode=final_answer_mode,
        )
