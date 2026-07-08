"""Shell tool implementation."""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

from agenttrust.schemas import ToolIntent, ToolResult


def _digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def shell(intent: ToolIntent, project_root: Path) -> ToolResult:
    simulated_output = intent.arguments.get("simulated_output")
    if isinstance(simulated_output, str):
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="ok",
            output_preview=simulated_output[:500],
            output_digest=_digest_text(simulated_output),
            metadata={"exit_code": 0, "duration_ms": 0, "simulated": True},
        )

    command = intent.arguments.get("command")
    if not isinstance(command, str) or not command:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error="shell requires a non-empty string command",
        )

    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=project_root,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    output = completed.stdout + completed.stderr
    status = "ok" if completed.returncode == 0 else "error"
    return ToolResult(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        status=status,
        output_preview=output[:500],
        output_digest=_digest_text(output),
        metadata={"exit_code": completed.returncode, "duration_ms": duration_ms},
        error=None if status == "ok" else f"shell exited with {completed.returncode}",
    )
