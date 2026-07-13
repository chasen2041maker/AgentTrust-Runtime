"""Use-case tests with in-memory ports and no filesystem adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agenttrust.application.build_context import BuildContextUseCase
from agenttrust.application.restore_run import RestoreRunUseCase
from agenttrust.application.run_fixture import FixtureIntent, FixtureRunRequest, RunFixtureUseCase
from agenttrust.application.run_tool import RunToolUseCase
from agenttrust.domain.decisions import FinalPermission, HookDecision, PermissionDecision, SandboxDecision
from agenttrust.domain.models import ToolIntent, ToolResult


class InMemoryEvidence:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def append(self, event_type: str, **payload: object) -> dict[str, object]:
        event = {"event_type": event_type, **payload}
        self.events.append(event)
        return event


class AllowPolicy:
    def decide(self, intent: ToolIntent) -> PermissionDecision:
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="allow",
            reason="test policy",
        )


class DenyPolicy:
    def decide(self, intent: ToolIntent) -> PermissionDecision:
        return PermissionDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="deny",
            reason="test denial",
        )


class AllowSandbox:
    def check(self, intent: ToolIntent) -> SandboxDecision:
        return SandboxDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="allow",
            reason="test sandbox",
        )


class RecordingExecutor:
    def __init__(self) -> None:
        self.executed: list[ToolIntent] = []

    def execute(self, intent: ToolIntent, _project_root: Path) -> ToolResult:
        self.executed.append(intent)
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="ok",
            output_preview="done",
        )


@dataclass(frozen=True)
class FakeFact:
    key: str

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key}


def _finalize(decision: PermissionDecision, _mode: str, _response: str | None) -> FinalPermission:
    return FinalPermission(effect=decision.effect, final_effect=decision.effect, reason=decision.reason)


def _hooks(intent: ToolIntent, _hooks: tuple[object, ...]) -> HookDecision:
    return HookDecision(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        effect="allow",
        hook_id=None,
        reason="no matching hook",
    )


def _intent() -> ToolIntent:
    return ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="read_file",
        arguments={"path": "README.md"},
        source="test",
        runtime_mode="test",
    )


def test_run_tool_use_case_executes_injected_ports_and_records_evidence(tmp_path: Path) -> None:
    evidence = InMemoryEvidence()
    executor = RecordingExecutor()
    stored: list[tuple[Path, tuple[FakeFact, ...]]] = []
    use_case = RunToolUseCase(
        evidence=evidence,
        policy_evaluator=AllowPolicy(),
        sandbox=AllowSandbox(),
        tool_executor=executor,
        finalize_permission=_finalize,
        evaluate_hooks=_hooks,
        map_facts=lambda _result: (FakeFact("answer"),),
        store_facts=lambda path, facts: stored.append((path, tuple(facts))),
    )

    intent = _intent()
    outcome = use_case.execute(
        intent,
        project_root=tmp_path,
        run_dir=tmp_path / "run",
        runtime_mode="test",
        facts_path=tmp_path / "facts.jsonl",
    )

    assert outcome.result is not None
    assert [event["event_type"] for event in evidence.events] == [
        "tool_intent",
        "permission_decision",
        "sandbox_decision",
        "tool_result",
        "fact_mapped",
    ]
    assert executor.executed == [intent]
    assert stored == [(tmp_path / "facts.jsonl", (FakeFact("answer"),))]


def test_run_tool_use_case_does_not_execute_when_policy_denies(tmp_path: Path) -> None:
    evidence = InMemoryEvidence()
    executor = RecordingExecutor()
    use_case = RunToolUseCase(
        evidence=evidence,
        policy_evaluator=DenyPolicy(),
        sandbox=AllowSandbox(),
        tool_executor=executor,
        finalize_permission=_finalize,
        evaluate_hooks=_hooks,
    )

    outcome = use_case.execute(
        _intent(),
        project_root=tmp_path,
        run_dir=tmp_path / "run",
        runtime_mode="test",
    )

    assert outcome.final_permission.final_effect == "deny"
    assert outcome.result is None
    assert executor.executed == []
    assert [event["event_type"] for event in evidence.events] == ["tool_intent", "permission_decision"]


def test_run_fixture_use_case_normalizes_fixture_intents(tmp_path: Path) -> None:
    evidence = InMemoryEvidence()
    executor = RecordingExecutor()
    tool_runner = RunToolUseCase(
        evidence=evidence,
        policy_evaluator=AllowPolicy(),
        sandbox=AllowSandbox(),
        tool_executor=executor,
        finalize_permission=_finalize,
        evaluate_hooks=_hooks,
    )
    use_case = RunFixtureUseCase(tool_runner)

    outcome = use_case.execute(
        FixtureRunRequest(
            name="fixture",
            tool_intents=(
                FixtureIntent(tool_name="read_file", arguments={"path": "README.md"}),
                FixtureIntent(tool_name="read_file", arguments={"path": "CHANGELOG.md"}, source="test"),
            ),
        ),
        run_id="run_fixture",
        project_root=tmp_path,
        run_dir=tmp_path / "run_fixture",
        runtime_mode="test",
    )

    assert outcome.run_id == "run_fixture"
    assert [result.intent.tool_call_id for result in outcome.outcomes] == ["call_001", "call_002"]
    assert [intent.source for intent in executor.executed] == ["fixture", "test"]


class InMemoryContextPacks:
    def build(self, project_root: Path, skill: str | None = None, budget: int = 4000) -> tuple[Path, Path]:
        return project_root / f"{skill}-{budget}.md", project_root / "manifest.json"

    def export_to_run(self, project_root: Path, run_id: str) -> tuple[Path, Path]:
        return project_root / run_id / "context.md", project_root / run_id / "manifest.json"


class InMemoryRecovery:
    def restore(
        self,
        run_dir: Path,
        only_file: str | None = None,
        dry_run: bool = True,
        force: bool = False,
    ) -> list[dict[str, object]]:
        return [{"run_dir": str(run_dir), "only_file": only_file, "dry_run": dry_run, "force": force}]


def test_context_and_restore_use_cases_delegate_to_ports(tmp_path: Path) -> None:
    context = BuildContextUseCase(InMemoryContextPacks())
    recovery = RestoreRunUseCase(InMemoryRecovery())

    assert context.build(tmp_path, skill="review", budget=512)[0].name == "review-512.md"
    assert context.export_to_run(tmp_path, "run_123")[0].parent.name == "run_123"
    assert recovery.execute(tmp_path / "run_123", only_file="README.md", dry_run=True) == [
        {"run_dir": str(tmp_path / "run_123"), "only_file": "README.md", "dry_run": True, "force": False}
    ]
