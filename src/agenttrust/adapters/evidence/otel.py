"""Export AgentTrust JSONL evidence as standard OpenTelemetry spans."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

from agenttrust.adapters.evidence.jsonl_store import read_trace


def export_otel_trace(
    run_dir: Path,
    *,
    endpoint: str | None = None,
    span_exporter: Any | None = None,
) -> int:
    """Emit a session hierarchy to a provided exporter or OTLP HTTP endpoint.

    JSONL remains the source of truth. This adapter reconstructs a portable
    observability view from verified-shape evidence after the session finishes.
    """

    try:
        trace_module = import_module("opentelemetry.sdk.trace")
        export_module = import_module("opentelemetry.sdk.trace.export")
    except ImportError as exc:
        raise RuntimeError("OpenTelemetry export requires agenttrust-runtime[otel]") from exc
    if span_exporter is None:
        if endpoint is None:
            raise ValueError("OTLP endpoint is required when no span_exporter is provided")
        try:
            otlp_module = import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        except ImportError as exc:
            raise RuntimeError("OTLP HTTP export requires agenttrust-runtime[otel]") from exc
        span_exporter = getattr(otlp_module, "OTLPSpanExporter")(endpoint=endpoint)

    provider = getattr(trace_module, "TracerProvider")()
    provider.add_span_processor(getattr(export_module, "SimpleSpanProcessor")(span_exporter))
    tracer = provider.get_tracer("agenttrust.runtime")
    events = read_trace(run_dir / "trace.jsonl")
    if not events:
        return 0
    root_event = next((event for event in events if isinstance(event.get("run_id"), str)), events[0])
    emitted = 0
    with tracer.start_as_current_span("agenttrust.session", attributes=_session_attributes(root_event)):
        emitted += 1
        calls = _events_by_tool_call(events)
        for call_events in calls.values():
            emitted += _emit_tool_spans(tracer, call_events)
        emitted += _emit_final_answer_spans(tracer, events)
    provider.force_flush()
    provider.shutdown()
    return emitted


def _events_by_tool_call(events: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    calls: dict[str, list[dict[str, object]]] = {}
    for event in events:
        call_id = event.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        calls.setdefault(call_id, []).append(event)
    return calls


def _emit_tool_spans(tracer: Any, events: list[dict[str, object]]) -> int:
    first = events[0]
    emitted = 0
    with tracer.start_as_current_span("agenttrust.tool", attributes=_tool_attributes(first)):
        emitted += 1
        for event in events:
            span_name = _stage_span_name(event.get("event_type"))
            if span_name is None:
                continue
            with tracer.start_as_current_span(span_name, attributes=_event_attributes(event)):
                emitted += 1
            if event.get("event_type") == "permission_decision" and event.get("approval_required") is True:
                with tracer.start_as_current_span("agenttrust.approval", attributes=_event_attributes(event)):
                    emitted += 1
    return emitted


def _emit_final_answer_spans(tracer: Any, events: list[dict[str, object]]) -> int:
    final_events = [event for event in events if event.get("event_type") in {"final_answer_submitted", "groundguard_check"}]
    if not final_events:
        return 0
    emitted = 0
    with tracer.start_as_current_span("agenttrust.final_answer", attributes=_event_attributes(final_events[0])):
        emitted += 1
        for event in final_events:
            if event.get("event_type") != "groundguard_check":
                continue
            with tracer.start_as_current_span("agenttrust.groundguard", attributes=_event_attributes(event)):
                emitted += 1
    return emitted


def _stage_span_name(event_type: object) -> str | None:
    stage_map = {
        "permission_decision": "agenttrust.policy",
        "hook_decision": "agenttrust.policy",
        "approval_request": "agenttrust.approval",
        "approval_requested": "agenttrust.approval",
        "approval_decided": "agenttrust.approval",
        "sandbox_decision": "agenttrust.sandbox",
        "tool_result": "agenttrust.execute",
    }
    return stage_map.get(event_type) if isinstance(event_type, str) else None


def _session_attributes(event: Mapping[str, object]) -> dict[str, object]:
    return {
        "agenttrust.run_id": event.get("run_id", ""),
        "agenttrust.session_id": event.get("session_id", ""),
        "agenttrust.actor_id": event.get("actor_id", ""),
        "agenttrust.agent_id": event.get("agent_id", ""),
        "agenttrust.policy_version": event.get("policy_version", ""),
    }


def _tool_attributes(event: Mapping[str, object]) -> dict[str, object]:
    return {
        **_session_attributes(event),
        "agenttrust.tool_call_id": event.get("tool_call_id", ""),
        "agenttrust.tool_name": event.get("tool_name", ""),
    }


def _event_attributes(event: Mapping[str, object]) -> dict[str, object]:
    attributes = _tool_attributes(event)
    attributes["agenttrust.event_type"] = event.get("event_type", "")
    for key in (
        "effect",
        "final_effect",
        "reason",
        "status",
        "approval_id",
        "decision",
        "mcp_transport",
    ):
        value = event.get(key)
        if isinstance(value, (str, bool, int, float)):
            attributes[f"agenttrust.{key}"] = value
    return attributes
