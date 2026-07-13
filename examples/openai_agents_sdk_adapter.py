"""Run a Session-scoped OpenAI Agents adapter without an API key."""

from __future__ import annotations

from pathlib import Path

from agenttrust import AgentTrustRuntime
from agenttrust.integrations.openai_agents import wrap_tools


def lookup_release_note(component: str) -> str:
    return f"{component}: session governance enabled"


def main(project_root: Path | None = None) -> str:
    """Use the dependency-free adapter path as a fake-model integration smoke test."""

    runtime = AgentTrustRuntime(project_root or Path.cwd(), runtime_mode="test")
    with runtime.session(actor_id="example-user", agent_id="openai-agents-example") as session:
        [tool] = wrap_tools([lookup_release_note], session=session, default_effect="ask", native=False)
        result = tool("AgentTrust Runtime")
        session.finalize_answer(result)
        return result


if __name__ == "__main__":
    print(main())
