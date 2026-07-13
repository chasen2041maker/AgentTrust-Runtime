"""Dependency-free fake-model tests for the official framework adapters."""

from __future__ import annotations

import pytest

from agenttrust import AgentTrustRuntime, ApprovalPending
from agenttrust.integrations import langgraph, openai_agents, pydantic_ai


def _fake_model(tools):
    add = tools[0]
    return add(20, 22), add(1, 2)


@pytest.mark.parametrize(
    "adapter",
    [
        lambda tools, session: openai_agents.wrap_tools(tools, session=session, default_effect="allow", native=False),
        lambda tools, session: langgraph.wrap_tools(tools, session=session, default_effect="allow", native=False),
        lambda tools, session: pydantic_ai.wrap_tools(tools, session=session, default_effect="allow"),
    ],
)
def test_framework_adapters_share_one_session_with_a_fake_model(tmp_path, adapter) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    with runtime.session(actor_id="alice") as session:
        tools = adapter([lambda left, right: left + right], session)
        assert _fake_model(tools) == (42, 3)

    assert session.session.status == "completed"


def test_pydantic_ai_register_tools_uses_agent_tool_plain(tmp_path) -> None:
    class FakePydanticAgent:
        def __init__(self) -> None:
            self.tools = []

        def tool_plain(self, tool):
            self.tools.append(tool)
            return tool

    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
    fake_agent = FakePydanticAgent()

    with runtime.session(actor_id="alice") as session:
        pydantic_ai.register_tools(fake_agent, [lambda value: value.upper()], session=session, default_effect="allow")
        assert fake_agent.tools[0]("trusted") == "TRUSTED"


@pytest.mark.parametrize(
    "adapter",
    [
        lambda tools, session: openai_agents.wrap_tools(tools, session=session, native=False),
        lambda tools, session: langgraph.wrap_tools(tools, session=session, native=False),
        lambda tools, session: pydantic_ai.wrap_tools(tools, session=session),
    ],
)
def test_framework_adapters_pause_for_approval(tmp_path, adapter) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")

    with runtime.session(actor_id="alice") as session:
        guarded = adapter([lambda value: value], session)[0]
        with pytest.raises(ApprovalPending):
            guarded("needs review")
        assert session.session.status == "waiting_approval"
