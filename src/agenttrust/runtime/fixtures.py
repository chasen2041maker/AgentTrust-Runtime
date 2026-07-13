"""Built-in deterministic fixture source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.policy.yaml_policy import snapshot_policy
from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.adapters.tools.gateway import ToolGateway
from agenttrust.application.run_tool import RunToolUseCase
from agenttrust.context_lite import build_context_pack, export_context_to_run
from agenttrust.adapters.verification.mapper import Fact, map_tool_result, write_facts
from agenttrust.groundguard_adapter import verify_answer, write_coverage_report
from agenttrust.memory_lite import add_memory, append_run_summary, list_memory
from agenttrust.permissions import (
    HookRule,
    PermissionEngine,
    evaluate_pre_tool_hooks,
    finalize_permission,
    load_policy,
    request_interactive_approval,
)
from agenttrust.runtime.recovery import create_backup_for_write
from agenttrust.schemas import ToolIntent
from agenttrust.skills_lite import load_skill


@dataclass(frozen=True)
class Fixture:
    name: str
    tool_intents: tuple[dict[str, object], ...]
    final_answer: str | None = None
    required_fact_keys: tuple[str, ...] = ()
    hooks: tuple[HookRule, ...] = ()
    skill: str | None = None
    memory_project: tuple[str, ...] = ()
    memory_decisions: tuple[str, ...] = ()
    context_skill: str | None = None
    context_budget: int | None = None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path
    trace_path: Path


BUILTIN_FIXTURES: dict[str, Fixture] = {
    "blocked_secret": Fixture(
        name="blocked_secret",
        tool_intents=(
            {
                "tool_name": "read_file",
                "arguments": {"path": ".env"},
            },
        ),
    ),
    "ask_noninteractive": Fixture(
        name="ask_noninteractive",
        tool_intents=(
            {
                "tool_name": "write_file",
                "arguments": {"path": "src/app.py", "content": "changed"},
            },
        ),
    ),
    "verified_answer": Fixture(
        name="verified_answer",
        tool_intents=(
            {
                "tool_name": "shell",
                "arguments": {
                    "command": "fixture verified revenue",
                    "simulated_output": "AGENTTRUST_FACTS:\nrevenue=3830000000 USD\nEND_AGENTTRUST_FACTS\n",
                },
            },
        ),
        final_answer="Revenue was $3.83 billion [fact:revenue].",
        required_fact_keys=("revenue",),
    ),
    "contradicted_answer": Fixture(
        name="contradicted_answer",
        tool_intents=(
            {
                "tool_name": "shell",
                "arguments": {
                    "command": "fixture contradicted revenue",
                    "simulated_output": "AGENTTRUST_FACTS:\nrevenue=3830000000 USD\nEND_AGENTTRUST_FACTS\n",
                },
            },
        ),
        final_answer="Revenue was $4.00 billion [fact:revenue].",
        required_fact_keys=("revenue",),
    ),
    "unverified_answer": Fixture(
        name="unverified_answer",
        tool_intents=(
            {
                "tool_name": "shell",
                "arguments": {
                    "command": "fixture unverified revenue",
                    "simulated_output": "AGENTTRUST_FACTS:\nrevenue=3830000000 USD\nEND_AGENTTRUST_FACTS\n",
                },
            },
        ),
        final_answer="Revenue was $9.99 billion.",
        required_fact_keys=("revenue",),
    ),
    "mcp_tool_denied": Fixture(
        name="mcp_tool_denied",
        tool_intents=(
            {
                "tool_name": "mcp_tool",
                "arguments": {
                    "server": "local-files",
                    "tool": "read_project_file",
                    "input": {"path": "README.md"},
                    "simulated": True,
                },
            },
        ),
    ),
    "mcp_tool_approved": Fixture(
        name="mcp_tool_approved",
        tool_intents=(
            {
                "tool_name": "mcp_tool",
                "arguments": {
                    "server": "local-files",
                    "tool": "read_project_file",
                    "input": {"path": "README.md"},
                    "simulated": True,
                },
            },
        ),
        final_answer="The mcp_tool_calls value is 1 [fact:mcp_tool_calls].",
        required_fact_keys=("mcp_tool_calls",),
    ),
    "skill_code_review": Fixture(
        name="skill_code_review",
        tool_intents=(
            {
                "tool_name": "git_diff",
                "source": "skill_lite",
                "arguments": {
                    "simulated_diff": (
                        "diff --git a/README.md b/README.md\n"
                        "--- a/README.md\n"
                        "+++ b/README.md\n"
                        "+verified roadmap coverage\n"
                    ),
                },
            },
        ),
        final_answer="The git_diff_files_changed value is 1 [fact:git_diff_files_changed].",
        required_fact_keys=("git_diff_files_changed",),
        skill="code-review",
    ),
    "skill_blocked_tool": Fixture(
        name="skill_blocked_tool",
        tool_intents=(
            {
                "tool_name": "shell",
                "source": "skill_lite",
                "arguments": {"command": "echo should not run"},
            },
        ),
        skill="code-review",
    ),
    "write_and_restore": Fixture(
        name="write_and_restore",
        tool_intents=(
            {
                "tool_name": "write_file",
                "arguments": {"path": "tmp/demo.txt", "content": "changed by agent"},
            },
        ),
    ),
    "blocked_by_hook": Fixture(
        name="blocked_by_hook",
        tool_intents=(
            {
                "tool_name": "write_file",
                "arguments": {"path": "src/app.py", "content": "changed"},
            },
        ),
        hooks=(
            HookRule(
                id="block-src-write",
                tool="write_file",
                path_glob="src/**",
                action="deny",
                reason="src writes blocked by hook",
            ),
        ),
    ),
    "memory_context_pack": Fixture(
        name="memory_context_pack",
        tool_intents=(
            {
                "tool_name": "skill_context",
                "arguments": {
                    "skill": "code-review",
                    "allowed_tools": ["read_file", "git_diff"],
                    "blocked_tools": ["shell", "write_file"],
                    "required_fact_keys": ["git_diff_files_changed"],
                },
            },
        ),
        memory_project=("GroundGuard verifies final numeric claims.",),
        memory_decisions=("Noninteractive ask is denied by default.",),
        context_skill="code-review",
        context_budget=1200,
    ),
}


def create_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"run_{timestamp}_{uuid4().hex[:8]}"


def list_fixtures() -> tuple[str, ...]:
    return tuple(sorted(BUILTIN_FIXTURES))


def get_fixture(name: str) -> Fixture:
    try:
        return BUILTIN_FIXTURES[name]
    except KeyError as exc:
        available = ", ".join(list_fixtures())
        raise ValueError(f"unknown fixture '{name}'. Available fixtures: {available}") from exc


def run_fixture(
    name: str,
    project_root: Path,
    runtime_mode: str = "interactive",
    gateway: ToolGateway | None = None,
    skill_override: str | None = None,
) -> RunResult:
    fixture = get_fixture(name)
    run_id = create_run_id()
    run_dir = project_root / ".agenttrust" / "runs" / run_id
    recorder = TraceRecorder(run_dir)
    gateway = gateway or ToolGateway()
    policy = load_policy(project_root / ".agenttrust" / "policy.yaml")
    permission_engine = PermissionEngine(policy)
    sandbox = PathSandbox(project_root)
    facts_path = run_dir / "facts.jsonl"
    decisions_path = run_dir / "decisions.json"
    decisions: list[Mapping[str, object]] = []
    all_facts: list[Fact] = []
    permission_counts = {"allow": 0, "ask": 0, "deny": 0}
    tool_result_count = 0
    coverage_status: str | None = None
    skill_name = skill_override or fixture.skill
    skill_info = load_skill(project_root, skill_name) if skill_name else None
    snapshot_path, policy_version = snapshot_policy(project_root / ".agenttrust" / "policy.yaml", run_dir)
    recorder.bind(
        actor_id=os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
        agent_id=os.environ.get("AGENTTRUST_AGENT_ID"),
        session_id=os.environ.get("AGENTTRUST_SESSION_ID"),
        policy_version=policy_version,
    )
    tool_runner = RunToolUseCase(
        evidence=recorder,
        policy_evaluator=permission_engine,
        sandbox=sandbox,
        tool_executor=gateway,
        finalize_permission=finalize_permission,
        evaluate_hooks=evaluate_pre_tool_hooks,
        request_approval=request_interactive_approval,
        create_recovery_checkpoint=create_backup_for_write,
        map_facts=map_tool_result,
        store_facts=write_facts,
    )

    recorder.append(
        "run_started",
        run_id=run_id,
        source="fixture",
        fixture_name=fixture.name,
        runtime_mode=runtime_mode,
        actor_id=os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
        agent_id=os.environ.get("AGENTTRUST_AGENT_ID"),
        session_id=os.environ.get("AGENTTRUST_SESSION_ID"),
    )
    recorder.append("policy_snapshot", run_id=run_id, policy_version=policy_version, path=str(snapshot_path))

    if skill_info is not None:
        recorder.append(
            "skill_loaded",
            run_id=run_id,
            skill_name=skill_info.name,
            allowed_tools=skill_info.policy.get("allowed_tools", []),
            blocked_tools=skill_info.policy.get("blocked_tools", []),
            required_fact_keys=skill_info.policy.get("required_fact_keys", []),
            output_contract=skill_info.policy.get("output_contract", {}),
        )

    for text in fixture.memory_project:
        path = add_memory(project_root, "project", text)
        recorder.append("memory_written", run_id=run_id, scope="project", path=str(path), text=text)
    for text in fixture.memory_decisions:
        path = add_memory(project_root, "decision", text)
        recorder.append("memory_written", run_id=run_id, scope="decision", path=str(path), text=text)
    if fixture.memory_project or fixture.memory_decisions or fixture.context_skill:
        memory = list_memory(project_root)
        memory_decisions = memory.get("decisions")
        memory_summaries = memory.get("run_summaries")
        recorder.append(
            "memory_loaded",
            run_id=run_id,
            project_memory_present=bool(memory.get("project")),
            decision_count=len(memory_decisions) if isinstance(memory_decisions, list) else 0,
            run_summary_count=len(memory_summaries) if isinstance(memory_summaries, list) else 0,
        )
    if fixture.context_skill:
        pack_path, manifest_path = build_context_pack(
            project_root,
            skill=fixture.context_skill,
            budget=fixture.context_budget or 4000,
        )
        run_pack_path, run_manifest_path = export_context_to_run(project_root, run_id)
        recorder.append(
            "context_pack_built",
            run_id=run_id,
            skill=fixture.context_skill,
            context_pack=str(pack_path),
            context_manifest=str(manifest_path),
            run_context_pack=str(run_pack_path),
            run_context_manifest=str(run_manifest_path),
            budget=fixture.context_budget or 4000,
        )

    for index, intent_spec in enumerate(fixture.tool_intents, start=1):
        tool_name = intent_spec["tool_name"]
        arguments = intent_spec.get("arguments", {})
        source = intent_spec.get("source", "fixture")
        if not isinstance(tool_name, str):
            raise TypeError("fixture tool_name must be a string")
        if not isinstance(arguments, dict):
            raise TypeError("fixture arguments must be a dictionary")
        if not isinstance(source, str):
            raise TypeError("fixture source must be a string")

        intent = ToolIntent(
            run_id=run_id,
            tool_call_id=f"call_{index:03d}",
            tool_name=tool_name,
            arguments=arguments,
            source=source,
            runtime_mode=runtime_mode,
        )
        if skill_info is not None:
            allowed_tools = set(str(tool) for tool in skill_info.policy.get("allowed_tools", []))
            blocked_tools = set(str(tool) for tool in skill_info.policy.get("blocked_tools", []))
            if intent.tool_name in blocked_tools or (allowed_tools and intent.tool_name not in allowed_tools):
                skill_decision = {
                    "run_id": run_id,
                    "tool_call_id": intent.tool_call_id,
                    "tool_name": intent.tool_name,
                    "effect": "deny",
                    "skill_name": skill_info.name,
                    "reason": "tool blocked by skill policy",
                }
                decisions.append(skill_decision)
                recorder.append("skill_decision", **skill_decision)
                continue
            skill_decision = {
                "run_id": run_id,
                "tool_call_id": intent.tool_call_id,
                "tool_name": intent.tool_name,
                "effect": "allow",
                "skill_name": skill_info.name,
                "reason": "tool allowed by skill policy",
            }
            decisions.append(skill_decision)
            recorder.append("skill_decision", **skill_decision)

        outcome = tool_runner.execute(
            intent,
            project_root=project_root,
            run_dir=run_dir,
            runtime_mode=runtime_mode,
            hooks=policy.hooks + fixture.hooks,
            facts_path=facts_path,
        )
        if outcome.hook_decision.hook_id is not None:
            decisions.append(outcome.hook_decision.to_dict())
        permission_counts[outcome.final_permission.final_effect] = (
            permission_counts.get(outcome.final_permission.final_effect, 0) + 1
        )
        decisions.append(
            {
                **outcome.permission_decision.to_dict(),
                **outcome.final_permission.to_dict(),
                "runtime_mode": runtime_mode,
            }
        )
        if outcome.sandbox_decision is not None and outcome.sandbox_decision.effect != "allow":
            decisions.append(outcome.sandbox_decision.to_dict())
        if outcome.result is not None:
            tool_result_count += 1
        all_facts.extend(cast(tuple[Fact, ...], outcome.facts))

    if fixture.final_answer is not None:
        (run_dir / "final-answer.md").write_text(fixture.final_answer, encoding="utf-8")
        recorder.append("final_answer", run_id=run_id, answer=fixture.final_answer)
        coverage_report = verify_answer(fixture.final_answer, all_facts, list(fixture.required_fact_keys))
        coverage_status = coverage_report.status
        write_coverage_report(run_dir / "groundguard-report.json", coverage_report)
        recorder.append("groundguard_check", run_id=run_id, **coverage_report.to_dict())

    summary_path = append_run_summary(
        project_root,
        {
            "run_id": run_id,
            "fixture_name": fixture.name,
            "tool_intent_count": len(fixture.tool_intents),
            "tool_result_count": tool_result_count,
            "permission_counts": permission_counts,
            "groundguard_status": coverage_status,
        },
    )
    recorder.append("memory_written", run_id=run_id, scope="run", path=str(summary_path))
    decisions_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    recorder.append("run_completed", run_id=run_id, status="completed")
    return RunResult(run_id=run_id, run_dir=run_dir, trace_path=recorder.trace_path)
