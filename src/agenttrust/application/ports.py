"""Ports used by application use cases to reach infrastructure."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from agenttrust.domain.decisions import PermissionDecision, SandboxDecision
from agenttrust.domain.models import ToolIntent, ToolResult


class EvidenceRecord(Protocol):
    """A serializable record emitted by an adapter."""

    def to_dict(self) -> Mapping[str, object]: ...


class EvidenceRecorderPort(Protocol):
    """Persist an execution evidence event."""

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]: ...


class PolicyEvaluatorPort(Protocol):
    """Evaluate policy for a normalized tool intent."""

    def decide(self, intent: ToolIntent) -> PermissionDecision: ...


class SandboxPort(Protocol):
    """Evaluate a sandbox profile for a normalized tool intent."""

    def check(self, intent: ToolIntent) -> SandboxDecision: ...


class ToolExecutorPort(Protocol):
    """Execute a permitted tool intent."""

    def execute(self, intent: ToolIntent, project_root: Path) -> ToolResult: ...


@runtime_checkable
class AsyncToolExecutorPort(Protocol):
    """Execute a permitted tool intent through an asynchronous transport."""

    async def execute_async(self, intent: ToolIntent, project_root: Path) -> ToolResult: ...


class RecoveryCheckpointPort(Protocol):
    """Create a recovery checkpoint before a mutating tool executes."""

    def __call__(self, intent: ToolIntent, project_root: Path, run_dir: Path) -> EvidenceRecord | None: ...


class RecoveryCheckpointBindingPort(Protocol):
    """Bind a pre-write backup to a successful, observed write result."""

    def __call__(
        self,
        intent: ToolIntent,
        result: ToolResult,
        checkpoint: EvidenceRecord,
        project_root: Path,
    ) -> EvidenceRecord | None: ...


class FactMapperPort(Protocol):
    """Map a tool result into independently verifiable facts."""

    def __call__(self, result: ToolResult) -> Sequence[EvidenceRecord]: ...


class FactStorePort(Protocol):
    """Persist facts produced during one tool call."""

    def __call__(self, path: Path, facts: Sequence[EvidenceRecord]) -> None: ...


class ApprovalJournalPort(Protocol):
    """Persist approval evidence events alongside a run's trace."""

    def append(self, event: Mapping[str, object]) -> None: ...


class ContextPackPort(Protocol):
    """Build and export a deterministic context pack."""

    def build(self, project_root: Path, skill: str | None = None, budget: int = 4000) -> tuple[Path, Path]: ...

    def export_to_run(self, project_root: Path, run_id: str) -> tuple[Path, Path]: ...


class RecoveryPort(Protocol):
    """Restore a previous mutating run through a recovery adapter."""

    def restore(
        self,
        run_dir: Path,
        only_file: str | None = None,
        dry_run: bool = True,
        force: bool = False,
    ) -> list[dict[str, object]]: ...
