"""Tool Gateway for normalized ToolIntent execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agenttrust.schemas import ToolIntent, ToolResult
from agenttrust.tools import git_diff, read_file, shell, write_file

ToolHandler = Callable[[ToolIntent, Path], ToolResult]


class ToolGateway:
    """Dispatch ToolIntent objects to built-in tool handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {
            "read_file": read_file,
            "write_file": write_file,
            "shell": shell,
            "git_diff": git_diff,
        }

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def execute(self, intent: ToolIntent, project_root: Path) -> ToolResult:
        handler = self._tools.get(intent.tool_name)
        if handler is None:
            return ToolResult(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                status="error",
                error=f"unknown tool: {intent.tool_name}",
                metadata={"available_tools": list(self.tool_names)},
            )
        return handler(intent, project_root)
