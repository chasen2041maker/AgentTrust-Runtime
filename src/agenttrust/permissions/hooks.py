"""Pre-tool hook evaluation."""

from __future__ import annotations

from agenttrust.domain.decisions import HookDecision
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import HookRule


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
