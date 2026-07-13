"""Pydantic AI adapters for Session-scoped governed Python tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from agenttrust.governance import govern
from agenttrust.interfaces.python_api import AgentTrustSession


def wrap_tools(
    tools: Iterable[Callable[..., Any]],
    *,
    session: AgentTrustSession,
    default_effect: str = "ask",
) -> list[Callable[..., Any]]:
    """Return governed functions suitable for Pydantic AI's `Agent.tool_plain`."""

    return [govern(tool, session=session, default_effect=default_effect) for tool in tools]


def register_tools(
    agent: Any,
    tools: Iterable[Callable[..., Any]],
    *,
    session: AgentTrustSession,
    default_effect: str = "ask",
) -> list[Callable[..., Any]]:
    """Register governed functions on a Pydantic AI Agent through `tool_plain`."""

    if not hasattr(agent, "tool_plain"):
        raise TypeError("Pydantic AI integration requires an agent with tool_plain")
    governed = wrap_tools(tools, session=session, default_effect=default_effect)
    for tool in governed:
        agent.tool_plain(tool)
    return governed
