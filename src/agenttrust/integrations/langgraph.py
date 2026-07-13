"""LangGraph and LangChain tool adapters for Session-scoped governance."""

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
    """Wrap functions for `ToolNode`, keeping all calls in the provided Session.

    When `langgraph` is installed, the default return value is compatible with
    LangChain's `ToolNode`. Set `native=False` for a dependency-free test loop.
    """

    governed = [govern(tool, session=session, default_effect=default_effect) for tool in tools]
    if not native:
        return list(governed)
    try:
        langchain_tool = getattr(import_module("langchain_core.tools"), "tool")
    except ImportError:
        return list(governed)
    return [langchain_tool(tool) for tool in governed]
