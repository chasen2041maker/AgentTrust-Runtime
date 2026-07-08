"""Built-in deterministic fixture source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from agenttrust.groundguard_adapter import map_tool_result, verify_answer, write_coverage_report, write_facts
from agenttrust.permissions import PathSandbox, PermissionEngine, finalize_permission, load_policy
from agenttrust.runtime.gateway import ToolGateway
from agenttrust.runtime.trace import TraceRecorder
from agenttrust.schemas import ToolIntent


@dataclass(frozen=True)
class Fixture:
    name: str
    tool_intents: tuple[dict[str, object], ...]
    final_answer: str | None = None
    required_fact_keys: tuple[str, ...] = ()


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
    decisions: list[dict[str, object]] = []
    all_facts = []

    recorder.append(
        "run_started",
        run_id=run_id,
        source="fixture",
        fixture_name=fixture.name,
        runtime_mode=runtime_mode,
    )

    for index, intent_spec in enumerate(fixture.tool_intents, start=1):
        tool_name = intent_spec["tool_name"]
        arguments = intent_spec.get("arguments", {})
        if not isinstance(tool_name, str):
            raise TypeError("fixture tool_name must be a string")
        if not isinstance(arguments, dict):
            raise TypeError("fixture arguments must be a dictionary")

        intent = ToolIntent(
            run_id=run_id,
            tool_call_id=f"call_{index:03d}",
            tool_name=tool_name,
            arguments=arguments,
            source="fixture",
            runtime_mode=runtime_mode,
        )
        recorder.append("tool_intent", **intent.to_dict())

        permission_decision = permission_engine.decide(intent)
        final_permission = finalize_permission(permission_decision, runtime_mode)
        permission_event = {
            **permission_decision.to_dict(),
            **final_permission.to_dict(),
            "runtime_mode": runtime_mode,
        }
        decisions.append(permission_event)
        recorder.append("permission_decision", **permission_event)
        if final_permission.final_effect != "allow":
            continue

        sandbox_decision = sandbox.check(intent)
        recorder.append("sandbox_decision", **sandbox_decision.to_dict())
        if sandbox_decision.effect != "allow":
            decisions.append(sandbox_decision.to_dict())
            continue

        result = gateway.execute(intent, project_root)
        recorder.append("tool_result", **result.to_dict())
        facts = map_tool_result(result)
        if facts:
            all_facts.extend(facts)
            write_facts(facts_path, facts)
        recorder.append(
            "fact_mapped",
            run_id=run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            fact_count=len(facts),
            facts=[fact.to_dict() for fact in facts],
        )

    if fixture.final_answer is not None:
        (run_dir / "final-answer.md").write_text(fixture.final_answer, encoding="utf-8")
        recorder.append("final_answer", run_id=run_id, answer=fixture.final_answer)
        coverage_report = verify_answer(fixture.final_answer, all_facts, list(fixture.required_fact_keys))
        write_coverage_report(run_dir / "groundguard-report.json", coverage_report)
        recorder.append("groundguard_check", run_id=run_id, **coverage_report.to_dict())

    decisions_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    recorder.append("run_completed", run_id=run_id, status="completed")
    return RunResult(run_id=run_id, run_dir=run_dir, trace_path=recorder.trace_path)
