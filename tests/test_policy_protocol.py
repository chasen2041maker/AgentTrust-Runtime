from __future__ import annotations

import json
from pathlib import Path

from agenttrust.adapters.policy.yaml_policy import load_policy
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import Policy, PolicyRule
from agenttrust.domain.protocol import DecisionRequest, POLICY_PROTOCOL_VERSION
from agenttrust.interfaces.cli import main
from agenttrust.permissions.diagnostics import lint_policy
from agenttrust.permissions.engine import PermissionEngine


def test_policy_protocol_explains_all_matching_rules_and_precedence() -> None:
    policy = Policy(
        rules=(
            PolicyRule(id="allow", tool="write_file", effect="allow", reason="known file"),
            PolicyRule(id="ask", tool="write_file", effect="ask", reason="confirmation"),
            PolicyRule(id="deny", tool="write_file", effect="deny", reason="protected"),
        )
    )
    intent = ToolIntent("run", "call", "write_file", {"path": "src/app.py"}, "test")

    explanation = PermissionEngine(policy).explain(DecisionRequest.from_intent(intent))

    assert explanation["response"]["effect"] == "deny"
    assert explanation["response"]["matched_rule_ids"] == ["allow", "ask", "deny"]
    assert [rule["id"] for rule in explanation["matched_rules"]] == ["allow", "ask", "deny"]
    assert explanation["precedence"][:2] == ["policy deny", "tool registry deny"]


def test_policy_protocol_preserves_legacy_decide_api() -> None:
    policy = Policy(rules=(PolicyRule(id="write", tool="write_file", effect="ask", reason="confirm"),))

    decision = PermissionEngine(policy).decide(ToolIntent("run", "call", "write_file", {"path": "x"}, "test"))

    assert decision.effect == "ask"
    request = DecisionRequest.from_intent(ToolIntent("run", "call", "read_file", {"path": "README.md"}, "test"))
    assert request.protocol_version == POLICY_PROTOCOL_VERSION
    assert request.arguments_digest.startswith("sha256:")


def test_lint_reports_duplicate_and_conflicting_rules() -> None:
    policy = Policy(
        rules=(
            PolicyRule(id="same", tool="read_file", effect="allow", reason=""),
            PolicyRule(id="same", tool="read_file", effect="deny", reason="blocked"),
        )
    )

    diagnostics = lint_policy(policy)

    assert {item["code"] for item in diagnostics} == {
        "duplicate_rule_id",
        "empty_reason",
        "conflicting_rule_precedence",
    }


def test_policy_cli_lint_test_and_explain(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    capsys.readouterr()
    fixtures = [
        {"id": "write", "tool": "write_file", "arguments": {"path": "src/main.py"}, "expected_effect": "ask"},
        {"id": "read", "tool": "read_file", "arguments": {"path": "README.md"}, "expected_effect": "allow"},
    ]
    (tmp_path / "policy-fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")

    assert main(["policy", "lint", ".agenttrust/policy.yaml"]) == 0
    assert json.loads(capsys.readouterr().out)["diagnostics"] == []
    assert main(["policy", "test", ".agenttrust/policy.yaml", "policy-fixtures.json"]) == 0
    assert all(item["passed"] for item in json.loads(capsys.readouterr().out)["results"])
    assert main(["policy", "explain", ".agenttrust/policy.yaml", "--tool", "write_file", "--path", "src/main.py"]) == 0
    assert json.loads(capsys.readouterr().out)["response"]["effect"] == "ask"


def test_policy_loader_records_protocol_version(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("policy_version: agenttrust.policy/v1\nrules: []\n", encoding="utf-8")

    assert load_policy(policy_path).protocol_version == POLICY_PROTOCOL_VERSION
