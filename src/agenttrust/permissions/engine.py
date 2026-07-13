"""Permission rule evaluation."""

from __future__ import annotations

from collections.abc import Mapping

from agenttrust.domain.decisions import PermissionDecision
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy
from agenttrust.domain.protocol import DecisionRequest, DecisionResponse, Obligation, POLICY_PROTOCOL_VERSION
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
        response = self.evaluate(DecisionRequest.from_intent(intent))
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect=response.effect,
            reason=response.reason,
            rule_id=response.policy_rule_id,
        )

    def evaluate(self, request: DecisionRequest) -> DecisionResponse:
        """Evaluate the stable v1 policy protocol without exposing raw arguments."""

        if request.protocol_version != POLICY_PROTOCOL_VERSION:
            raise ValueError(f"unsupported policy protocol version: {request.protocol_version}")
        intent = request.to_intent()
        default_decision = self._default_tool_decision(intent)
        matching_decisions = self._matching_rule_decisions(intent)
        matched_rule_ids = [decision.rule_id for decision in matching_decisions if decision.rule_id is not None]
        deny_match = next((decision for decision in matching_decisions if decision.effect == "deny"), None)
        if deny_match is not None:
            return _response_from_decision(deny_match, matched_rule_ids)
        ask_match = next((decision for decision in matching_decisions if decision.effect == "ask"), None)
        allow_match = next((decision for decision in matching_decisions if decision.effect == "allow"), None)
        if default_decision is not None and default_decision.effect == "deny":
            # Registry denials are hard boundaries: policy may tighten them, never elevate them.
            return _response_from_decision(default_decision, matched_rule_ids)
        if ask_match is not None:
            return _response_from_decision(ask_match, matched_rule_ids)
        if allow_match is not None:
            return _response_from_decision(allow_match, matched_rule_ids)
        if default_decision is not None:
            return _response_from_decision(default_decision, matched_rule_ids)
        return _response_from_decision(PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="allow",
            reason="no matching policy rule",
        ), matched_rule_ids)

    def _matching_rule_decisions(self, intent: ToolIntent) -> list[PermissionDecision]:
        decisions: list[PermissionDecision] = []
        for rule in self.policy.rules:
            if not rule.matches(intent):
                continue
            decisions.append(
                PermissionDecision(
                    run_id=intent.run_id,
                    tool_call_id=intent.tool_call_id,
                    tool_name=intent.tool_name,
                    effect=rule.effect,
                    reason=rule.reason,
                    rule_id=rule.id,
                )
            )
        return decisions

    def explain(self, request: DecisionRequest) -> dict[str, object]:
        """Return all matching rules and the precedence-selected v1 response."""

        intent = request.to_intent()
        matched = self._matching_rule_decisions(intent)
        response = self.evaluate(request)
        return {
            "request": request.to_dict(),
            "matched_rules": [
                {"id": decision.rule_id, "effect": decision.effect, "reason": decision.reason}
                for decision in matched
            ],
            "tool_default": self._default_tool_decision(intent).to_dict(),
            "precedence": ["policy deny", "tool registry deny", "policy ask", "policy allow", "tool default"],
            "response": response.to_dict(),
        }

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


def _response_from_decision(
    decision: PermissionDecision, matched_rule_ids: list[str]
) -> DecisionResponse:
    obligations: tuple[Obligation, ...] = ()
    if decision.effect == "ask":
        obligations = (Obligation(type="require_approval"),)
    return DecisionResponse(
        protocol_version=POLICY_PROTOCOL_VERSION,
        effect=decision.effect,
        reason=decision.reason,
        policy_rule_id=decision.rule_id,
        matched_rule_ids=tuple(matched_rule_ids),
        obligations=obligations,
    )
