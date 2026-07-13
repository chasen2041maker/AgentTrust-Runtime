"""Filesystem path-sandbox adapter for local tools."""

from __future__ import annotations

import os
from pathlib import Path

from agenttrust.domain.decisions import SandboxDecision
from agenttrust.domain.models import ToolIntent


class PathSandbox:
    """Constrain local file tool paths to the configured project root."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def check(self, intent: ToolIntent) -> SandboxDecision:
        if intent.tool_name not in {"read_file", "write_file"}:
            return SandboxDecision(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                effect="allow",
                reason="tool has no path sandbox requirement",
            )

        path_value = intent.arguments.get("path")
        if not isinstance(path_value, str) or not path_value:
            return self._deny(intent, "path argument is required", None)

        target = Path(path_value).expanduser()
        if not target.is_absolute():
            target = self.project_root / target

        check_path = target.parent if intent.tool_name == "write_file" else target
        resolved = check_path.resolve(strict=False)
        final_target = (resolved / target.name).resolve(strict=False) if intent.tool_name == "write_file" else resolved

        if self._is_system_path(final_target):
            return self._deny(intent, "system paths are blocked", final_target)
        if not self._is_inside_project(final_target):
            return self._deny(intent, "path escapes project_root", final_target)
        if self._is_secret_path(final_target):
            return self._deny(intent, "secret files are blocked", final_target)

        return SandboxDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="allow",
            reason="path allowed",
            path=str(final_target),
        )

    def _deny(self, intent: ToolIntent, reason: str, path: Path | None) -> SandboxDecision:
        return SandboxDecision(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            effect="deny",
            reason=reason,
            path=str(path) if path is not None else None,
        )

    def _is_inside_project(self, path: Path) -> bool:
        try:
            path.relative_to(self.project_root)
            return True
        except ValueError:
            return False

    def _is_secret_path(self, path: Path) -> bool:
        normalized_parts = {part.lower() for part in path.parts}
        return (
            path.name.lower() == ".env"
            or path.suffix.lower() == ".pem"
            or (".ssh" in normalized_parts)
        )

    def _is_system_path(self, path: Path) -> bool:
        resolved = str(path).lower()
        if os.name == "nt":
            blocked_prefixes = (
                str(Path(os.environ.get("SystemRoot", r"C:\Windows"))).lower(),
                str(Path(os.environ.get("ProgramFiles", r"C:\Program Files"))).lower(),
                str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))).lower(),
            )
            return any(resolved.startswith(prefix) for prefix in blocked_prefixes)
        return any(resolved.startswith(prefix) for prefix in ("/etc", "/bin", "/usr", "/var", "/root"))
