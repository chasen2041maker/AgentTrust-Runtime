"""Permission rule evaluation."""

from __future__ import annotations

from agenttrust.domain.decisions import PermissionDecision
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy
from agenttrust.tools.registry import get_tool_spec


class PermissionEngine:
    """Evaluate ToolIntent objects against policy rules."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def decide(self, intent: ToolIntent) -> PermissionDecision:
        ask_match: PermissionDecision | None = None
        for rule in self.policy.rules:
            if not rule.matches(intent):
                continue
            decision = PermissionDecision(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                effect=rule.effect,
                reason=rule.reason,
                rule_id=rule.id,
            )
            if rule.effect == "deny":
                return decision
            if rule.effect == "ask" and ask_match is None:
                ask_match = decision
        if ask_match is not None:
            return ask_match
        default_decision = self._default_tool_decision(intent)
        if default_decision is not None:
            return default_decision
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="allow",
            reason="no matching policy rule",
        )

    def _default_tool_decision(self, intent: ToolIntent) -> PermissionDecision | None:
        try:
            spec = get_tool_spec(intent.tool_name)
        except ValueError:
            return None
        if spec.default_effect == "allow":
            return None
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect=spec.default_effect,
            reason=f"tool registry default effect: {spec.default_effect}",
            rule_id=f"tool-default:{intent.tool_name}",
        )
