"""Tests for reconstructing OpenTelemetry spans from AgentTrust evidence."""

from __future__ import annotations

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.otel import export_otel_trace


def test_otel_export_reconstructs_session_tool_and_final_answer_hierarchy(tmp_path) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
    with runtime.session(actor_id="alice", session_id="otel_session") as session:
        session.execute(
            "shell",
            {"simulated_output": "AGENTTRUST_FACTS:\nrevenue=42 USD\nEND_AGENTTRUST_FACTS\n"},
        )
        session.finalize_answer("Revenue was 42 [fact:revenue].", required_fact_keys=["revenue"])

    exporter = InMemorySpanExporter()
    count = export_otel_trace(session.run_dir, span_exporter=exporter)
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}

    assert count == len(spans)
    assert {
        "agenttrust.session",
        "agenttrust.tool",
        "agenttrust.policy",
        "agenttrust.approval",
        "agenttrust.sandbox",
        "agenttrust.execute",
        "agenttrust.final_answer",
        "agenttrust.groundguard",
    } <= names
    root = next(span for span in spans if span.name == "agenttrust.session")
    tool = next(span for span in spans if span.name == "agenttrust.tool")
    assert tool.parent.span_id == root.context.span_id
    assert root.attributes["agenttrust.session_id"] == "otel_session"
