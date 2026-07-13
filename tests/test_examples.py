"""The published integration examples run without framework installs or API keys."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("examples/openai_agents_sdk_adapter.py", "AgentTrust Runtime: session governance enabled"),
        ("examples/langgraph_tool_adapter.py", "reviewed: MCP schema drift is denied"),
        ("examples/pydantic_ai_adapter.py", "governed request: write documentation"),
    ],
)
def test_integration_example_runs_without_api_key(tmp_path: Path, relative_path: str, expected: str) -> None:
    namespace = runpy.run_path(ROOT / relative_path)

    assert namespace["main"](tmp_path) == expected
    assert any((tmp_path / ".agenttrust" / "runs").iterdir())
