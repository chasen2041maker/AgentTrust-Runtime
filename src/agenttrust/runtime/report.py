"""Minimal replay and report helpers."""

from __future__ import annotations

from pathlib import Path

from agenttrust.runtime.trace import read_trace


def resolve_run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / ".agenttrust" / "runs" / run_id


def timeline_lines(run_dir: Path) -> list[str]:
    events = read_trace(run_dir / "trace.jsonl")
    lines: list[str] = []
    for event in events:
        event_type = event.get("event_type", "unknown")
        tool_name = event.get("tool_name")
        status = event.get("status")
        if tool_name and status:
            lines.append(f"{event_type}: {tool_name} -> {status}")
        elif tool_name:
            lines.append(f"{event_type}: {tool_name}")
        else:
            lines.append(str(event_type))
    return lines


def write_markdown_report(run_dir: Path) -> Path:
    events = read_trace(run_dir / "trace.jsonl")
    report_path = run_dir / "report.md"
    lines = ["# AgentTrust Run Report", ""]
    for event in events:
        event_type = event.get("event_type", "unknown")
        lines.append(f"## {event_type}")
        if "tool_name" in event:
            lines.append(f"- tool: `{event['tool_name']}`")
        if "status" in event:
            lines.append(f"- status: `{event['status']}`")
        if "error" in event and event["error"]:
            lines.append(f"- error: {event['error']}")
        if "output_preview" in event and event["output_preview"]:
            lines.append("")
            lines.append("```text")
            lines.append(str(event["output_preview"]))
            lines.append("```")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
