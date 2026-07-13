"""Application use case for deterministic context-pack operations."""

from __future__ import annotations

from pathlib import Path

from agenttrust.application.ports import ContextPackPort


class BuildContextUseCase:
    """Build or export context through an injected context-pack adapter."""

    def __init__(self, context_packs: ContextPackPort) -> None:
        self._context_packs = context_packs

    def build(self, project_root: Path, skill: str | None = None, budget: int = 4000) -> tuple[Path, Path]:
        return self._context_packs.build(project_root, skill=skill, budget=budget)

    def export_to_run(self, project_root: Path, run_id: str) -> tuple[Path, Path]:
        return self._context_packs.export_to_run(project_root, run_id)
