"""Run a Session-scoped LangGraph adapter without a model or API key."""

from __future__ import annotations

from pathlib import Path

from agenttrust import AgentTrustRuntime
from agenttrust.integrations.langgraph import wrap_tools


def summarize_change(change: str) -> str:
    return f"reviewed: {change}"


def main(project_root: Path | None = None) -> str:
    """Use a plain callable as a fake LangGraph ToolNode invocation."""

    runtime = AgentTrustRuntime(project_root or Path.cwd(), runtime_mode="test")
    with runtime.session(actor_id="example-user", agent_id="langgraph-example") as session:
        [tool] = wrap_tools([summarize_change], session=session, default_effect="ask", native=False)
        result = tool("MCP schema drift is denied")
        session.finalize_answer(result)
        return result


if __name__ == "__main__":
    print(main())
