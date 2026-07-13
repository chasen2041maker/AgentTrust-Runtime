"""Immutable policy, approval, hook, and sandbox decision records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDecision:
    """The policy engine's result for a normalized tool intent."""

    run_id: str
    tool_call_id: str
    tool_name: str
    effect: str
    reason: str
    rule_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "effect": self.effect,
            "reason": self.reason,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True)
class FinalPermission:
    """The enforceable permission after approval handling."""

    effect: str
    final_effect: str
    reason: str
    approval_required: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "effect": self.effect,
            "final_effect": self.final_effect,
            "reason": self.reason,
            "approval_required": self.approval_required,
        }


@dataclass(frozen=True)
class HookDecision:
    """The result of applying pre-tool hook rules."""

    run_id: str
    tool_call_id: str
    tool_name: str
    effect: str
    hook_id: str | None
    reason: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "effect": self.effect,
            "hook_id": self.hook_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SandboxDecision:
    """The result of applying a sandbox profile to a tool intent."""

    run_id: str
    tool_call_id: str
    tool_name: str
    effect: str
    reason: str
    path: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "effect": self.effect,
            "reason": self.reason,
            "path": self.path,
        }
