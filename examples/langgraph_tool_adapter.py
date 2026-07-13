"""Adapter pattern for routing a LangGraph-style tool node through AgentTrust."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agenttrust.interfaces.python_api import AgentTrustRuntime


def governed_tool_node(state: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Accept a normalized node state with `tool_name` and `arguments` fields."""
    result = AgentTrustRuntime(project_root, runtime_mode="interactive").execute(
        str(state["tool_name"]),
        dict(state.get("arguments", {})),
        source="langgraph",
    )
    return {
        **state,
        "agenttrust_run_id": result.run_id,
        "tool_result": result.outcome.result.to_dict() if result.outcome.result else None,
        "permission": result.outcome.final_permission.to_dict(),
    }
