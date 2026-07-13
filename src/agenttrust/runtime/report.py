"""Minimal replay and report helpers."""

from __future__ import annotations

from pathlib import Path

import html
import json

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
        if event_type == "permission_decision":
            lines.append(
                f"permission_decision: {tool_name} {event.get('effect')} -> {event.get('final_effect')} ({event.get('reason')})"
            )
        elif event_type == "sandbox_decision":
            lines.append(f"sandbox_decision: {tool_name} -> {event.get('effect')} ({event.get('reason')})")
        elif event_type == "groundguard_check":
            lines.append(f"groundguard_check: {event.get('status')}")
        elif tool_name and status:
            lines.append(f"{event_type}: {tool_name} -> {status}")
        elif tool_name:
            lines.append(f"{event_type}: {tool_name}")
        else:
            lines.append(str(event_type))
    return lines


def write_markdown_report(run_dir: Path) -> Path:
    events = read_trace(run_dir / "trace.jsonl")
    coverage = _read_json(run_dir / "groundguard-report.json")
    report_path = run_dir / "report.md"
    lines = ["# AgentTrust Run Report", ""]
    if coverage:
        required_facts = coverage.get("required_fact_keys")
        required_facts_text = ", ".join(str(item) for item in required_facts) if isinstance(required_facts, list) else ""
        lines.extend(
            [
                "## GroundGuard Coverage",
                f"- status: `{coverage.get('status')}`",
                f"- required facts: `{required_facts_text}`",
                "",
            ]
        )
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


def write_html_report(run_dir: Path) -> Path:
    markdown_path = write_markdown_report(run_dir)
    html_path = run_dir / "report.html"
    markdown = markdown_path.read_text(encoding="utf-8")
    body = "\n".join(f"<pre>{html.escape(line)}</pre>" for line in markdown.splitlines())
    html_path.write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>AgentTrust Run Report</title></head>"
        f"<body>{body}</body></html>",
        encoding="utf-8",
    )
    return html_path


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
