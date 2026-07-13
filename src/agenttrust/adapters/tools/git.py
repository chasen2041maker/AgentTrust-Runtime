"""Git tool implementations."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from agenttrust.domain.models import ToolIntent, ToolResult


def _digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _diff_stats(diff_text: str) -> dict[str, int]:
    files_changed = 0
    added_lines = 0
    deleted_lines = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            files_changed += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted_lines += 1
    return {
        "files_changed": files_changed,
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
    }


def git_diff(intent: ToolIntent, project_root: Path) -> ToolResult:
    simulated_diff = intent.arguments.get("simulated_diff")
    if isinstance(simulated_diff, str):
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="ok",
            output_preview=simulated_diff[:500],
            output_digest=_digest_text(simulated_diff),
            metadata={
                "exit_code": 0,
                **_diff_stats(simulated_diff),
                "simulated": True,
            },
        )

    try:
        completed = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error=str(exc),
        )

    output = completed.stdout
    metadata = {
        "exit_code": completed.returncode,
        **_diff_stats(output),
    }
    if completed.returncode != 0:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            output_preview=output[:500],
            output_digest=_digest_text(output),
            metadata=metadata,
            error=completed.stderr.strip() or "git diff failed",
        )

    return ToolResult(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        status="ok",
        output_preview=output[:500],
        output_digest=_digest_text(output),
        metadata=metadata,
    )
