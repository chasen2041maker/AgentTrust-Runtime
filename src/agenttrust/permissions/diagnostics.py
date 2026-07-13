"""Static diagnostics and deterministic fixtures for policy protocol v1."""

from __future__ import annotations

from collections import Counter

from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy, PolicyRule
from agenttrust.permissions.engine import PermissionEngine


def lint_policy(policy: Policy) -> list[dict[str, str]]:
    """Return stable diagnostics without changing policy semantics."""

    diagnostics: list[dict[str, str]] = []
    identifiers = Counter(rule.id for rule in policy.rules)
    for rule_id in sorted(identifier for identifier, count in identifiers.items() if count > 1):
        diagnostics.append({"level": "error", "code": "duplicate_rule_id", "rule_id": rule_id})
    for rule in policy.rules:
        if not rule.reason.strip():
            diagnostics.append({"level": "warning", "code": "empty_reason", "rule_id": rule.id})
    for left_index, left in enumerate(policy.rules):
        for right in policy.rules[left_index + 1 :]:
            if _match_signature(left) == _match_signature(right) and left.effect != right.effect:
                diagnostics.append(
                    {
                        "level": "warning",
                        "code": "conflicting_rule_precedence",
                        "rule_id": f"{left.id},{right.id}",
                    }
                )
    return diagnostics


def run_policy_fixtures(policy: Policy, fixtures: object) -> list[dict[str, object]]:
    """Evaluate portable fixture cases and return their observed effects."""

    cases = fixtures.get("cases", ()) if isinstance(fixtures, dict) else fixtures
    if not isinstance(cases, list):
        raise ValueError("policy test fixture must be a JSON list or an object with a cases list")
    engine = PermissionEngine(policy)
    results: list[dict[str, object]] = []
    for index, raw_case in enumerate(cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"fixture case {index} must be an object")
        tool = raw_case.get("tool")
        arguments = raw_case.get("arguments", {})
        expected_effect = raw_case.get("expected_effect")
        if not isinstance(tool, str) or not tool:
            raise ValueError(f"fixture case {index} requires a tool")
        if not isinstance(arguments, dict):
            raise ValueError(f"fixture case {index} arguments must be an object")
        if expected_effect not in {"allow", "ask", "deny"}:
            raise ValueError(f"fixture case {index} requires expected_effect allow, ask, or deny")
        decision = engine.decide(
            ToolIntent(
                run_id="policy-test",
                tool_call_id=f"case-{index}",
                tool_name=tool,
                arguments=arguments,
                source="policy_test",
                runtime_mode=str(raw_case.get("runtime_mode", "test")),
            )
        )
        results.append(
            {
                "case": str(raw_case.get("id", index)),
                "expected_effect": expected_effect,
                "actual_effect": decision.effect,
                "passed": decision.effect == expected_effect,
                "rule_id": decision.rule_id,
            }
        )
    return results


def _match_signature(rule: PolicyRule) -> tuple[object, ...]:
    return (rule.tool, rule.paths, rule.command_patterns, rule.argv_patterns)
