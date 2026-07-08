"""Pre-tool hook evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from agenttrust.schemas import ToolIntent


@dataclass(frozen=True)
class HookRule:
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
class HookDecision:
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


def evaluate_pre_tool_hooks(intent: ToolIntent, hooks: tuple[HookRule, ...]) -> HookDecision:
    for hook in hooks:
        if hook.matches(intent):
            effect = "deny" if hook.action == "deny" else "allow"
            return HookDecision(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                effect=effect,
                hook_id=hook.id,
                reason=hook.reason,
            )
    return HookDecision(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        effect="allow",
        hook_id=None,
        reason="no matching hook",
    )
