from __future__ import annotations

from pathlib import Path
import tomllib

import agenttrust


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_enterprise_architecture_docs_are_linked() -> None:
    expected_docs = [
        "docs/enterprise-architecture.md",
        "docs/refactor-roadmap.md",
    ]
    for relative_path in expected_docs:
        assert (ROOT / relative_path).exists()

    readme = _read("README.md")
    docs_index = _read("docs/index.md")
    for link in expected_docs:
        assert link in readme
        assert link.removeprefix("docs/") in docs_index


def test_enterprise_architecture_cites_reference_sources() -> None:
    architecture = _read("docs/enterprise-architecture.md")
    required_sources = [
        "https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices",
        "https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/",
        "https://developers.openai.com/api/docs/guides/agents",
        "https://openai.github.io/openai-agents-python/tracing/",
        "https://learn.microsoft.com/en-us/agent-framework/overview/",
        "https://github.com/microsoft/agent-governance-toolkit",
        "https://www.nist.gov/itl/ai-risk-management-framework",
    ]

    for source in required_sources:
        assert source in architecture


def test_release_metadata_and_readme_describe_the_current_runtime() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    readme = _read("README.md")
    readme_zh = _read("README_zh.md")

    assert project["project"]["version"] == "0.5.2"
    assert agenttrust.__version__ == "0.5.2"
    for marker in (
        "AgentTrustSession",
        "Local MCP stdio governance",
        "OpenTelemetry",
        "security-v1",
        "107 deterministic checks",
        "agenttrust benchmark security",
    ):
        assert marker in readme
    for marker in (
        "为 AI Agent 的每一次工具调用增加策略、审批、恢复和可验证证据。",
        "本地 MCP stdio 治理",
        "107 个确定性检查",
        "Beta / 开发者预览",
    ):
        assert marker in readme_zh
    assert "36 passed" not in readme


def test_readmes_link_to_the_declared_license() -> None:
    license_text = _read("LICENSE")

    assert license_text.startswith("MIT License")
    for relative_path in ("README.md", "README_zh.md"):
        assert "[MIT](LICENSE)" in _read(relative_path)
