"""Application use case for restoring a governed run."""

from __future__ import annotations

from pathlib import Path

from agenttrust.application.ports import RecoveryPort


class RestoreRunUseCase:
    """Delegate restore requests to an injected recovery adapter."""

    def __init__(self, recovery: RecoveryPort) -> None:
        self._recovery = recovery

    def execute(
        self,
        run_dir: Path,
        only_file: str | None = None,
        dry_run: bool = True,
        force: bool = False,
    ) -> list[dict[str, object]]:
        return self._recovery.restore(run_dir, only_file=only_file, dry_run=dry_run, force=force)
