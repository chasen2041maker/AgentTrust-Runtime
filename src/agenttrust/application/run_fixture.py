"""Application-level fixture input model and runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agenttrust.application.run_tool import RunToolUseCase, ToolRunOutcome
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.policy import HookRule


@dataclass(frozen=True)
class FixtureIntent:
    """One fixture request before it is normalized into a tool intent."""

    tool_name: str
    arguments: dict[str, Any]
    source: str = "fixture"


@dataclass(frozen=True)
class FixtureRunRequest:
    """Framework-neutral fixture input for deterministic execution tests."""

    name: str
    tool_intents: tuple[FixtureIntent, ...]
    hooks: tuple[HookRule, ...] = ()


@dataclass(frozen=True)
class FixtureRunOutcome:
    """The per-intent results produced by a fixture run."""

    run_id: str
    outcomes: tuple[ToolRunOutcome, ...] = field(default_factory=tuple)


class RunFixtureUseCase:
    """Normalize fixture inputs and dispatch each through the tool use case."""

    def __init__(self, tool_runner: RunToolUseCase) -> None:
        self._tool_runner = tool_runner

    def execute(
        self,
        request: FixtureRunRequest,
        *,
        run_id: str,
        project_root: Path,
        run_dir: Path,
        runtime_mode: str,
        facts_path: Path | None = None,
    ) -> FixtureRunOutcome:
        outcomes: list[ToolRunOutcome] = []
        for index, fixture_intent in enumerate(request.tool_intents, start=1):
            intent = ToolIntent(
                run_id=run_id,
                tool_call_id=f"call_{index:03d}",
                tool_name=fixture_intent.tool_name,
                arguments=fixture_intent.arguments,
                source=fixture_intent.source,
                runtime_mode=runtime_mode,
            )
            outcomes.append(
                self._tool_runner.execute(
                    intent,
                    project_root=project_root,
                    run_dir=run_dir,
                    runtime_mode=runtime_mode,
                    hooks=request.hooks,
                    facts_path=facts_path,
                )
            )
        return FixtureRunOutcome(run_id=run_id, outcomes=tuple(outcomes))
