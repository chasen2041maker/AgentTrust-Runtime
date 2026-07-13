"""Tests for reconstructing OpenTelemetry spans from AgentTrust evidence."""

from __future__ import annotations

import pytest

from agenttrust import AgentTrustRuntime
from agenttrust.adapters.evidence.jsonl_store import read_trace
from agenttrust.adapters.evidence.otel import _timestamp_ns, export_otel_trace


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
    events = read_trace(session.run_dir / "trace.jsonl")
    assert tool.parent.span_id == root.context.span_id
    assert root.attributes["agenttrust.session_id"] == "otel_session"
    assert root.start_time == _timestamp_ns(events[0])
    assert root.end_time == _timestamp_ns(events[-1])


def test_otel_export_rejects_invalid_evidence_before_exporting(tmp_path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
    with runtime.session(actor_id="alice") as session:
        session.execute("read_file", {"path": "missing.txt"})

    trace_path = session.run_dir / "trace.jsonl"
    trace_path.write_text(trace_path.read_text(encoding="utf-8").replace("run_started", "tampered", 1), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid evidence trace"):
        export_otel_trace(session.run_dir, span_exporter=object())
