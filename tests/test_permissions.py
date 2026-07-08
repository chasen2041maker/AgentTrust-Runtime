from __future__ import annotations

from agenttrust.permissions import PermissionEngine, finalize_permission
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
