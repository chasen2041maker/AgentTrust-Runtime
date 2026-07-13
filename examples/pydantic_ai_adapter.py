"""Run a Session-scoped Pydantic AI adapter without a model or API key."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from agenttrust import AgentTrustRuntime
from agenttrust.integrations.pydantic_ai import register_tools


class FakePydanticAgent:
    """The minimal `tool_plain` surface needed for a dependency-free example."""

    def __init__(self) -> None:
        self.tools: list[Callable[[str], str]] = []

    def tool_plain(self, tool: Callable[[str], str]) -> Callable[[str], str]:
        self.tools.append(tool)
        return tool


def classify_request(request: str) -> str:
    return f"governed request: {request}"


def main(project_root: Path | None = None) -> str:
    runtime = AgentTrustRuntime(project_root or Path.cwd(), runtime_mode="test")
    agent = FakePydanticAgent()
    with runtime.session(actor_id="example-user", agent_id="pydantic-ai-example") as session:
        register_tools(agent, [classify_request], session=session, default_effect="ask")
        result = agent.tools[0]("write documentation")
        session.finalize_answer(result)
        return result


if __name__ == "__main__":
    print(main())
