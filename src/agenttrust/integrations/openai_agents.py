"""OpenAI Agents SDK adapters for Session-scoped governed Python tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Any

from agenttrust.governance import govern
from agenttrust.interfaces.python_api import AgentTrustSession


def wrap_tools(
    tools: Iterable[Callable[..., Any]],
    *,
    session: AgentTrustSession,
    default_effect: str = "ask",
    native: bool = True,
) -> list[object]:
    """Wrap Python functions for an OpenAI Agent while preserving one AgentTrust Session.

    With `openai-agents` installed, the default result is a list of native
    `FunctionTool` instances. Set `native=False` for framework-free testing.
    """

    governed = [govern(tool, session=session, default_effect=default_effect) for tool in tools]
    if not native:
        return list(governed)
    try:
        function_tool = getattr(import_module("agents"), "function_tool")
    except ImportError:
        return list(governed)
    return [function_tool(tool) for tool in governed]
