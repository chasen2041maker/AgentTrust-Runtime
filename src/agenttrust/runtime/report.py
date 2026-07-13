"""Minimal replay and report helpers."""

from __future__ import annotations

from pathlib import Path

import html
from agenttrust.adapters.evidence.jsonl_store import read_verified_events


def resolve_run_dir(project_root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must name one run directory")
    runs_root = (project_root / ".agenttrust" / "runs").resolve()
    run_dir = (runs_root / run_id).resolve()
    if run_dir.parent != runs_root:
        raise ValueError("run_id escapes the runs directory")
    return run_dir


def timeline_lines(run_dir: Path) -> list[str]:
    events = read_verified_events(run_dir)
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
    events = read_verified_events(run_dir)
    coverage = _groundguard_coverage(events)
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


def _groundguard_coverage(events: list[dict[str, object]]) -> dict[str, object]:
    for event in reversed(events):
        if event.get("event_type") == "groundguard_check":
            return dict(event)
    return {}
