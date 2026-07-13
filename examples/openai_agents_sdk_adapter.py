"""Adapter pattern for routing an OpenAI Agents SDK tool call through AgentTrust."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agenttrust.interfaces.python_api import AgentTrustRuntime


def execute_agent_tool(project_root: Path, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Use from a tool callback after normalizing the framework call arguments."""
    result = AgentTrustRuntime(project_root, runtime_mode="interactive").execute(
        tool_name,
        arguments,
        source="openai_agents_sdk",
    )
    outcome = result.outcome
    return {
        "run_id": result.run_id,
        "status": outcome.result.status if outcome.result else outcome.final_permission.final_effect,
        "output": outcome.result.output_preview if outcome.result else outcome.final_permission.reason,
    }
