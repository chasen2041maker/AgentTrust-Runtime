from __future__ import annotations

from pathlib import Path


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
