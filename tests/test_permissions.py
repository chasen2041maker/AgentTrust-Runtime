from __future__ import annotations

from agenttrust.permissions import PermissionEngine, finalize_permission, request_interactive_approval
from pathlib import Path

from agenttrust.permissions.policy import Policy, PolicyRule, load_policy
from agenttrust.schemas import ToolIntent


def test_first_deny_wins_over_ask() -> None:
    policy = Policy(
        rules=(
            PolicyRule(id="ask", tool="shell", effect="ask", reason="approval"),
            PolicyRule(id="deny", tool="shell", effect="deny", reason="danger", command_patterns=("rm -rf /",)),
        )
    )
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="shell",
        arguments={"command": "rm -rf /"},
        source="test",
    )

    decision = PermissionEngine(policy).decide(intent)

    assert decision.effect == "deny"
    assert decision.rule_id == "deny"


def test_noninteractive_ask_finalizes_to_deny() -> None:
    policy = Policy(rules=(PolicyRule(id="ask", tool="write_file", effect="ask", reason="approval"),))
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="write_file",
        arguments={"path": "src/app.py", "content": "x"},
        source="test",
    )
    decision = PermissionEngine(policy).decide(intent)

    final = finalize_permission(decision, "noninteractive")

    assert final.final_effect == "deny"
    assert final.reason == "approval_required"


def test_interactive_approval_response_controls_ask_decision() -> None:
    policy = Policy(rules=(PolicyRule(id="ask", tool="write_file", effect="ask", reason="approval"),))
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="write_file",
        arguments={"path": "src/app.py", "content": "x"},
        source="test",
    )
    decision = PermissionEngine(policy).decide(intent)

    approved = finalize_permission(decision, "interactive", "approve")
    denied = finalize_permission(decision, "interactive", "deny")

    assert request_interactive_approval(decision, input_func=lambda _prompt: "yes") == "approve"
    assert approved.final_effect == "allow"
    assert approved.reason == "interactive_approved"
    assert denied.final_effect == "deny"
    assert denied.reason == "interactive_denied"


def test_default_policy_denies_dangerous_shell(tmp_path: Path) -> None:
    policy = load_policy(tmp_path / "missing-policy.yaml")
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="shell",
        arguments={"command": "rm -rf /"},
        source="test",
    )

    decision = PermissionEngine(policy).decide(intent)

    assert decision.effect == "deny"
    assert decision.rule_id == "deny-dangerous-shell"


def test_tool_registry_default_effect_is_safety_fallback() -> None:
    policy = Policy(rules=())
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="mcp_tool",
        arguments={"server": "local-files", "tool": "read_project_file"},
        source="test",
    )

    decision = PermissionEngine(policy).decide(intent)

    assert decision.effect == "ask"
    assert decision.rule_id == "tool-default:mcp_tool"


def test_unregistered_tool_is_denied_before_gateway_execution() -> None:
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="not_registered",
        arguments={},
        source="test",
    )

    decision = PermissionEngine(Policy()).decide(intent)

    assert decision.effect == "deny"
    assert decision.reason == "unregistered_tool"
    assert decision.rule_id == "tool-registry:unregistered"


def test_shell_registry_default_requires_approval() -> None:
    intent = ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name="shell",
        arguments={"argv": ["echo", "safe"]},
        source="test",
    )

    decision = PermissionEngine(Policy()).decide(intent)

    assert decision.effect == "ask"
    assert decision.rule_id == "tool-default:shell"
