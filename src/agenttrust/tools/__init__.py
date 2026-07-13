"""Built-in tool implementations."""

from agenttrust.adapters.tools.file import read_file, write_file
from agenttrust.adapters.tools.git import git_diff
from agenttrust.adapters.tools.mcp import mcp_tool
from agenttrust.tools.registry import ToolSpec, get_tool_spec, list_tool_specs
from agenttrust.adapters.tools.shell import shell
from agenttrust.adapters.tools.skill import skill_context

__all__ = [
    "ToolSpec",
    "get_tool_spec",
    "git_diff",
    "list_tool_specs",
    "mcp_tool",
    "read_file",
    "shell",
    "skill_context",
    "write_file",
]
