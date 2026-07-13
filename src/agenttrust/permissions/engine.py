"""Permission rule evaluation."""

from __future__ import annotations

from collections.abc import Mapping

from agenttrust.domain.decisions import PermissionDecision
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy
from agenttrust.tools.registry import ToolSpec, get_tool_spec


class PermissionEngine:
    """Evaluate ToolIntent objects against policy rules."""

    def __init__(self, policy: Policy, tool_specs: Mapping[str, ToolSpec] | None = None) -> None:
        self.policy = policy
        self._tool_specs = dict(tool_specs or {})

    def register_tool_spec(self, spec: ToolSpec) -> None:
        existing = self._tool_specs.get(spec.name)
        if existing is not None and existing != spec:
            raise ValueError(f"tool spec is already registered for {spec.name}")
        self._tool_specs[spec.name] = spec

    def decide(self, intent: ToolIntent) -> PermissionDecision:
        default_decision = self._default_tool_decision(intent)
        ask_match: PermissionDecision | None = None
        allow_match: PermissionDecision | None = None
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
            if rule.effect == "allow" and allow_match is None:
                allow_match = decision
        if default_decision is not None and default_decision.effect == "deny":
            # Registry denials are hard boundaries: policy may tighten them, never elevate them.
            return default_decision
        if ask_match is not None:
            return ask_match
        if allow_match is not None:
            return allow_match
        if default_decision is not None:
            return default_decision
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="allow",
            reason="no matching policy rule",
        )

    def _default_tool_decision(self, intent: ToolIntent) -> PermissionDecision:
        spec = self._tool_specs.get(intent.tool_name)
        if spec is None:
            try:
                spec = get_tool_spec(intent.tool_name)
            except ValueError:
                spec = None
        if spec is None:
            return PermissionDecision(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                effect="deny",
                reason="unregistered_tool",
                rule_id="tool-registry:unregistered",
            )
        if spec.default_effect == "allow":
            return PermissionDecision(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                effect="allow",
                reason="tool registry default effect: allow",
                rule_id=f"tool-default:{intent.tool_name}",
            )
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect=spec.default_effect,
            reason=f"tool registry default effect: {spec.default_effect}",
            rule_id=f"tool-default:{intent.tool_name}",
        )
