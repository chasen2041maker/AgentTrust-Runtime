"""Local tool-executor adapter for registered built-in tools."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agenttrust.domain.models import ToolIntent, ToolResult
from agenttrust.adapters.tools.file import read_file, write_file
from agenttrust.adapters.tools.shell import shell
from agenttrust.adapters.tools.git import git_diff
from agenttrust.tools import mcp_tool, skill_context


ToolHandler = Callable[[ToolIntent, Path], ToolResult]


class ToolGateway:
    """Dispatch normalized tool intents to local concrete handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {
            "read_file": read_file,
            "write_file": write_file,
            "shell": shell,
            "git_diff": git_diff,
            "mcp_tool": mcp_tool,
            "skill_context": skill_context,
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
