"""Local tool-executor adapter for registered built-in tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from agenttrust.domain.models import ToolIntent, ToolResult
from agenttrust.adapters.tools.file import read_file, write_file
from agenttrust.adapters.tools.shell import shell, unsafe_shell_command
from agenttrust.adapters.tools.git import git_diff
from agenttrust.adapters.tools.mcp import mcp_tool
from agenttrust.adapters.tools.skill import skill_context


ToolHandler = Callable[[ToolIntent, Path], ToolResult]
AsyncToolHandler = Callable[[ToolIntent, Path], Awaitable[ToolResult]]


class ToolGateway:
    """Dispatch normalized tool intents to local concrete handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {
            "read_file": read_file,
            "write_file": write_file,
            "shell": shell,
            "unsafe_shell_command": unsafe_shell_command,
            "git_diff": git_diff,
            "mcp_tool": mcp_tool,
            "skill_context": skill_context,
        }
        self._async_tools: dict[str, AsyncToolHandler] = {}

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def register(self, name: str, handler: ToolHandler) -> None:
        existing = self._tools.get(name)
        if existing is not None and existing is not handler:
            raise ValueError(f"tool handler is already registered for {name}")
        self._tools[name] = handler

    def register_async(self, name: str, handler: AsyncToolHandler) -> None:
        existing = self._async_tools.get(name)
        if existing is not None and existing is not handler:
            raise ValueError(f"async tool handler is already registered for {name}")
        self._async_tools[name] = handler

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

    async def execute_async(self, intent: ToolIntent, project_root: Path) -> ToolResult:
        """Use native async handlers directly; preserve built-ins through an explicit bridge."""

        async_handler = self._async_tools.get(intent.tool_name)
        if async_handler is not None:
            return await async_handler(intent, project_root)
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
        return await asyncio.to_thread(handler, intent, project_root)
