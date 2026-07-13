"""Tests for Session-bound GroundGuard final-answer completion."""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.cli import main


def test_finalize_answer_binds_groundguard_report_to_the_active_session(tmp_path: Path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice", session_id="session_final") as session:
        session.execute(
            "shell",
            {
                "simulated_output": "AGENTTRUST_FACTS:\nrevenue=3830000000 USD\nEND_AGENTTRUST_FACTS\n",
            },
        )
        result = session.finalize_answer(
            "Revenue was $3.83 billion [fact:revenue].",
            required_fact_keys=["revenue"],
        )

    assert result.status == "verified"
    assert result.completed is True
    assert result.completion_action == "completed"
    assert session.session.status == "completed"
    assert (session.run_dir / "final-answer.md").exists()
    assert (session.run_dir / "groundguard-report.json").exists()
    events = read_trace(session.run_dir / "trace.jsonl")
    assert "final_answer_submitted" in [event["event_type"] for event in events]
    assert "groundguard_check" in [event["event_type"] for event in events]
    assert "session_completed" in [event["event_type"] for event in events]
    assert verify_trace(session.run_dir / "trace.jsonl")["valid"] is True


@pytest.mark.parametrize(
    ("mode", "expected_action"),
    [("require_revision", "revision_required"), ("deny_completion", "completion_denied")],
)
def test_incomplete_final_answer_respects_policy_completion_mode(
    tmp_path: Path, mode: str, expected_action: str
) -> None:
    (tmp_path / "README.md").write_text("one line\n", encoding="utf-8")
    agenttrust_dir = tmp_path / ".agenttrust"
    agenttrust_dir.mkdir()
    (agenttrust_dir / "policy.yaml").write_text(
        f"""project_root: .
final_answer:
  on_incomplete: {mode}
rules: []
""",
        encoding="utf-8",
    )
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice") as session:
        session.execute("read_file", {"path": "README.md"})
        incomplete = session.finalize_answer("No cited facts.", required_fact_keys=["read_file_lines"])
        assert incomplete.status == "unverified"
        assert incomplete.completed is False
        assert incomplete.completion_action == expected_action
        assert session.session.status == "running"
        verified = session.finalize_answer(
            "README has 1 lines [fact:read_file_lines].",
            required_fact_keys=["read_file_lines"],
        )
        assert verified.status == "verified"
        assert verified.completed is True

    assert session.session.status == "completed"


def test_final_answer_cannot_use_facts_from_a_different_session(tmp_path: Path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
    with runtime.session(actor_id="alice") as source_session:
        source_session.execute(
            "shell",
            {"simulated_output": "AGENTTRUST_FACTS:\nrevenue=42 USD\nEND_AGENTTRUST_FACTS\n"},
        )

    with runtime.session(actor_id="alice") as isolated_session:
        result = isolated_session.finalize_answer("Revenue was 42 [fact:revenue].", required_fact_keys=["revenue"])

    assert result.status == "unverified"


def test_simulated_facts_are_test_only_and_cannot_verify_a_normal_session(tmp_path: Path) -> None:
    agenttrust_dir = tmp_path / ".agenttrust"
    agenttrust_dir.mkdir()
    (agenttrust_dir / "policy.yaml").write_text(
        """project_root: .
rules:
  - id: allow-shell-for-test-harness
    tool: shell
    effect: allow
    reason: explicit harness policy
""",
        encoding="utf-8",
    )
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="interactive", allow_simulation=True)

    with runtime.session(actor_id="alice") as session:
        tool_run = session.execute(
            "shell",
            {"simulated_output": "AGENTTRUST_FACTS:\nrevenue=42 USD\nEND_AGENTTRUST_FACTS\n"},
        )
        result = session.finalize_answer("Revenue was 42 [fact:revenue].", required_fact_keys=["revenue"])

    assert tool_run.outcome.result is not None
    assert tool_run.outcome.facts[0].provenance == "simulated"
    assert tool_run.outcome.facts[0].trust_level == "test_only"
    assert result.status == "unverified"


def test_policy_can_require_groundguard_for_completion(tmp_path: Path, monkeypatch) -> None:
    import agenttrust.adapters.verification.verifier as verifier

    monkeypatch.setattr(verifier, "FactGate", None)
    monkeypatch.setattr(verifier, "report_to_versioned_dict", None)
    agenttrust_dir = tmp_path / ".agenttrust"
    agenttrust_dir.mkdir()
    (agenttrust_dir / "policy.yaml").write_text(
        """project_root: .
verification:
  mode: groundguard_required
final_answer:
  on_incomplete: deny_completion
rules: []
""",
        encoding="utf-8",
    )
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice") as session:
        session.execute(
            "shell",
            {"simulated_output": "AGENTTRUST_FACTS:\nrevenue=42 USD\nEND_AGENTTRUST_FACTS\n"},
        )
        result = session.finalize_answer("Revenue was 42 [fact:revenue].", required_fact_keys=["revenue"])

    assert result.status == "unverified"
    assert result.completed is False
    assert result.completion_action == "completion_denied"


def test_resumed_session_uses_its_persisted_fact_ledger_for_final_answer(tmp_path: Path, capsys) -> None:
    (tmp_path / "README.md").write_text("one line\n", encoding="utf-8")
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
    with runtime.session(actor_id="alice") as waiting_session:
        waiting_session.execute("read_file", {"path": "README.md"})
        pending = waiting_session.execute("write_file", {"path": "resumed.txt", "content": "done"})

    assert pending.approval_request is not None
    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                pending.approval_request.approval_id,
                "--reason",
                "reviewed",
            ]
        )
        == 0
    )
    capsys.readouterr()

    restarted_runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
    with restarted_runtime.resume(waiting_session.run_id) as resumed_session:
        resumed_session.resume_pending_approval()
        result = resumed_session.finalize_answer(
            "README has 1 lines [fact:read_file_lines].",
            required_fact_keys=["read_file_lines"],
        )

    assert result.status == "verified"
    assert result.completed is True
