"""Skill context pseudo-tool."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agenttrust.domain.models import ToolIntent, ToolResult


def skill_context(intent: ToolIntent, project_root: Path) -> ToolResult:
    skill = str(intent.arguments.get("skill", "unknown"))
    allowed = intent.arguments.get("allowed_tools", [])
    blocked = intent.arguments.get("blocked_tools", [])
    required = intent.arguments.get("required_fact_keys", [])
    output = (
        "AGENTTRUST_FACTS:\n"
        f"skill_allowed_tools_count={len(allowed) if isinstance(allowed, list) else 0} count\n"
        f"skill_blocked_tools_count={len(blocked) if isinstance(blocked, list) else 0} count\n"
        "END_AGENTTRUST_FACTS\n"
    )
    return ToolResult(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        status="ok",
        output_preview=output,
        output_digest="sha256:" + hashlib.sha256(output.encode("utf-8")).hexdigest(),
        metadata={
            "skill_name": skill,
            "skill_allowed_tools_count": len(allowed) if isinstance(allowed, list) else 0,
            "skill_blocked_tools_count": len(blocked) if isinstance(blocked, list) else 0,
            "skill_required_fact_keys_count": len(required) if isinstance(required, list) else 0,
        },
    )
