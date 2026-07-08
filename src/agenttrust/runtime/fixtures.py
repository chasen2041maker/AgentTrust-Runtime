"""Built-in deterministic fixture source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agenttrust.runtime.gateway import ToolGateway
from agenttrust.runtime.trace import TraceRecorder
from agenttrust.schemas import ToolIntent


@dataclass(frozen=True)
class Fixture:
    name: str
    tool_intents: tuple[dict[str, object], ...]
    final_answer: str | None = None


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
                "tool_name": "read_file",
                "arguments": {"path": "README.md"},
            },
        ),
        final_answer="Revenue was $3.83 billion [fact:revenue].",
    ),
    "contradicted_answer": Fixture(
        name="contradicted_answer",
        tool_intents=(
            {
                "tool_name": "git_diff",
                "arguments": {},
            },
        ),
        final_answer="Revenue was $4.00 billion [fact:revenue].",
    ),
    "unverified_answer": Fixture(
        name="unverified_answer",
        tool_intents=(
            {
                "tool_name": "git_diff",
                "arguments": {},
            },
        ),
        final_answer="Revenue was $9.99 billion.",
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
        result = gateway.execute(intent, project_root)
        recorder.append("tool_result", **result.to_dict())

    if fixture.final_answer is not None:
        recorder.append("final_answer", run_id=run_id, answer=fixture.final_answer)

    recorder.append("run_completed", run_id=run_id, status="completed")
    return RunResult(run_id=run_id, run_dir=run_dir, trace_path=recorder.trace_path)
