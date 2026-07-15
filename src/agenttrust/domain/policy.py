"""Pure policy and hook rules for governed tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
import shlex
from typing import Any

from agenttrust.domain.models import ToolIntent
from agenttrust.domain.protocol import POLICY_PROTOCOL_VERSION


VALID_EFFECTS = frozenset({"allow", "ask", "deny"})
VALID_HOOK_ACTIONS = frozenset({"deny"})
VALID_FINAL_ANSWER_MODES = frozenset({"warn", "deny_completion", "require_revision"})
VALID_VERIFICATION_MODES = frozenset({"fallback", "groundguard_required"})


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
                argv = _normalized_argv(intent.arguments.get("argv"))
                command = shlex.join(argv) if argv is not None else None
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

    def to_dict(self) -> dict[str, object]:
        """Return the normalized, portable representation enforced at runtime."""

        payload: dict[str, object] = {
            "id": self.id,
            "tool": self.tool,
            "effect": self.effect,
            "reason": self.reason,
        }
        if self.paths:
            payload["paths"] = list(self.paths)
        if self.command_patterns:
            payload["command_patterns"] = list(self.command_patterns)
        if self.argv_patterns:
            payload["argv_patterns"] = [list(pattern) for pattern in self.argv_patterns]
        return payload


def _normalized_argv(raw_argv: object) -> tuple[str, ...] | None:
    if not isinstance(raw_argv, list) or not raw_argv:
        return None
    if not all(isinstance(token, str) and token for token in raw_argv):
        return None
    normalized = [token.replace("\\", "/") for token in raw_argv]
    normalized[0] = normalized[0].rsplit("/", 1)[-1]
    return tuple(token.lower() for token in normalized)


def _argv_pattern_matches(argv: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    """Match normalized argv tokens; ** matches zero or more tokens anywhere."""

    normalized_pattern = tuple(token.lower() for token in pattern)

    def matches(argv_index: int, pattern_index: int) -> bool:
        if pattern_index == len(normalized_pattern):
            return argv_index == len(argv)
        token_pattern = normalized_pattern[pattern_index]
        if token_pattern == "**":
            return any(matches(next_index, pattern_index + 1) for next_index in range(argv_index, len(argv) + 1))
        return (
            argv_index < len(argv)
            and fnmatch(argv[argv_index], token_pattern)
            and matches(argv_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


@dataclass(frozen=True)
class HookRule:
    """A pre-tool control evaluated before permission finalization."""

    id: str
    tool: str
    action: str
    reason: str
    path_glob: str | None = None

    def __post_init__(self) -> None:
        if self.action not in VALID_HOOK_ACTIONS:
            raise ValueError(f"invalid hook action: {self.action}; pre-tool hooks may only deny")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HookRule":
        when = raw.get("when", {}) or {}
        if not isinstance(when, dict):
            when = {}
        path_glob = raw.get("path_glob", when.get("path_glob"))
        action = str(raw.get("action", "deny"))
        return cls(
            id=str(raw.get("id", "unnamed-hook")),
            tool=str(raw.get("tool", when.get("tool", "*"))),
            action=action,
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

    def to_dict(self) -> dict[str, object]:
        """Return the normalized pre-tool hook representation."""

        when: dict[str, object] = {"tool": self.tool}
        if self.path_glob is not None:
            when["path_glob"] = self.path_glob
        return {"id": self.id, "when": when, "action": self.action, "reason": self.reason}


@dataclass(frozen=True)
class Policy:
    """A framework-free collection of policy and hook rules."""

    project_root: str = "."
    mode: str = "default"
    rules: tuple[PolicyRule, ...] = field(default_factory=tuple)
    hooks: tuple[HookRule, ...] = field(default_factory=tuple)
    final_answer_mode: str = "warn"
    verification_mode: str = "fallback"
    approval_ttl_seconds: int = 3600
    protocol_version: str = POLICY_PROTOCOL_VERSION

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Policy":
        protocol_version = str(raw.get("policy_version", POLICY_PROTOCOL_VERSION))
        if protocol_version != POLICY_PROTOCOL_VERSION:
            raise ValueError(f"unsupported policy protocol version: {protocol_version}")
        final_answer = raw.get("final_answer", {}) or {}
        if not isinstance(final_answer, dict):
            raise ValueError("final_answer policy must contain a mapping")
        final_answer_mode = str(final_answer.get("on_incomplete", "warn"))
        if final_answer_mode not in VALID_FINAL_ANSWER_MODES:
            raise ValueError(f"invalid final_answer on_incomplete mode: {final_answer_mode}")
        verification = raw.get("verification", {}) or {}
        if not isinstance(verification, dict):
            raise ValueError("verification policy must contain a mapping")
        verification_mode = str(verification.get("mode", "fallback"))
        if verification_mode not in VALID_VERIFICATION_MODES:
            raise ValueError(f"invalid verification mode: {verification_mode}")
        approvals = raw.get("approvals", {}) or {}
        if not isinstance(approvals, dict):
            raise ValueError("approvals policy must contain a mapping")
        approval_ttl_seconds = approvals.get("default_ttl_seconds", 3600)
        if (
            isinstance(approval_ttl_seconds, bool)
            or not isinstance(approval_ttl_seconds, int)
            or approval_ttl_seconds <= 0
        ):
            raise ValueError("approvals.default_ttl_seconds must be a positive integer")
        return cls(
            project_root=str(raw.get("project_root", ".")),
            protocol_version=protocol_version,
            mode=str(raw.get("mode", "default")),
            rules=tuple(PolicyRule.from_dict(rule) for rule in raw.get("rules", ()) or ()),
            hooks=tuple(
                HookRule.from_dict(hook)
                for hook in ((raw.get("hooks", {}) or {}).get("pre_tool", ()) or ())
            ),
            final_answer_mode=final_answer_mode,
            verification_mode=verification_mode,
            approval_ttl_seconds=approval_ttl_seconds,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the full normalized policy semantics used by the runtime."""

        payload: dict[str, object] = {
            "policy_version": self.protocol_version,
            "project_root": self.project_root,
            "mode": self.mode,
            "final_answer": {"on_incomplete": self.final_answer_mode},
            "verification": {"mode": self.verification_mode},
            "approvals": {"default_ttl_seconds": self.approval_ttl_seconds},
            "rules": [rule.to_dict() for rule in self.rules],
        }
        if self.hooks:
            payload["hooks"] = {"pre_tool": [hook.to_dict() for hook in self.hooks]}
        return payload
