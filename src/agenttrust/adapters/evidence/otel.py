"""Export AgentTrust JSONL evidence as standard OpenTelemetry spans."""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_events


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

    trace_path = run_dir / "trace.jsonl"
    events = read_trace(trace_path)
    verification = verify_events(events)
    if verification["valid"] is not True:
        raise ValueError(f"cannot export invalid evidence trace: {verification.get('reason', 'unknown')}")
    if not events:
        return 0
    try:
        api_trace_module = import_module("opentelemetry.trace")
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
    root_event = next((event for event in events if isinstance(event.get("run_id"), str)), events[0])
    emitted = 0
    root_span = tracer.start_span(
        "agenttrust.session",
        attributes=_session_attributes(root_event),
        start_time=_timestamp_ns(root_event),
    )
    try:
        with getattr(api_trace_module, "use_span")(root_span, end_on_exit=False):
            emitted += 1
            calls = _events_by_tool_call(events)
            for call_events in calls.values():
                emitted += _emit_tool_spans(tracer, api_trace_module, call_events)
            emitted += _emit_final_answer_spans(tracer, api_trace_module, events)
    finally:
        root_span.end(end_time=_timestamp_ns(events[-1]))
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


def _emit_tool_spans(tracer: Any, api_trace_module: Any, events: list[dict[str, object]]) -> int:
    first = events[0]
    emitted = 0
    tool_span = tracer.start_span(
        "agenttrust.tool",
        attributes=_tool_attributes(first),
        start_time=_timestamp_ns(first),
    )
    try:
        with getattr(api_trace_module, "use_span")(tool_span, end_on_exit=False):
            emitted += 1
            for event in events:
                span_name = _stage_span_name(event.get("event_type"))
                if span_name is None:
                    continue
                emitted += _emit_event_span(tracer, span_name, event)
                if event.get("event_type") == "permission_decision" and event.get("approval_required") is True:
                    emitted += _emit_event_span(tracer, "agenttrust.approval", event)
    finally:
        tool_span.end(end_time=_timestamp_ns(events[-1]))
    return emitted


def _emit_final_answer_spans(tracer: Any, api_trace_module: Any, events: list[dict[str, object]]) -> int:
    final_events = [event for event in events if event.get("event_type") in {"final_answer_submitted", "groundguard_check"}]
    if not final_events:
        return 0
    emitted = 0
    final_span = tracer.start_span(
        "agenttrust.final_answer",
        attributes=_event_attributes(final_events[0]),
        start_time=_timestamp_ns(final_events[0]),
    )
    try:
        with getattr(api_trace_module, "use_span")(final_span, end_on_exit=False):
            emitted += 1
            for event in final_events:
                if event.get("event_type") != "groundguard_check":
                    continue
                emitted += _emit_event_span(tracer, "agenttrust.groundguard", event)
    finally:
        final_span.end(end_time=_timestamp_ns(final_events[-1]))
    return emitted


def _emit_event_span(tracer: Any, name: str, event: Mapping[str, object]) -> int:
    timestamp = _timestamp_ns(event)
    span = tracer.start_span(name, attributes=_event_attributes(event), start_time=timestamp)
    span.end(end_time=timestamp)
    return 1


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
    metadata = event.get("metadata")
    metadata_values = metadata if isinstance(metadata, Mapping) else {}
    for key in (
        "effect",
        "final_effect",
        "reason",
        "status",
        "approval_id",
        "decision",
        "mcp_transport",
        "mcp_execution_mode",
        "mcp_simulation_explicit",
    ):
        value = event.get(key, metadata_values.get(key))
        if isinstance(value, (str, bool, int, float)):
            attributes[f"agenttrust.{key}"] = value
    return attributes


def _timestamp_ns(event: Mapping[str, object]) -> int:
    created_at = event.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("evidence event requires an ISO-8601 created_at timestamp")
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid evidence event timestamp: {created_at}") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"evidence event timestamp must include a timezone: {created_at}")
    seconds = int(timestamp.timestamp())
    return seconds * 1_000_000_000 + timestamp.microsecond * 1_000
