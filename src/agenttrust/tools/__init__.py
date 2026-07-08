"""Built-in tool implementations."""

from agenttrust.tools.file import read_file, write_file
from agenttrust.tools.git import git_diff
from agenttrust.tools.mcp import mcp_tool
from agenttrust.tools.registry import ToolSpec, get_tool_spec, list_tool_specs
from agenttrust.tools.shell import shell
from agenttrust.tools.skill import skill_context

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
