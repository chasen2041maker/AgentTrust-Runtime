"""File tool implementations."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agenttrust.schemas import ToolIntent, ToolResult


def _digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_file(intent: ToolIntent, project_root: Path) -> ToolResult:
    path_arg = intent.arguments.get("path")
    if not isinstance(path_arg, str) or not path_arg:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error="read_file requires a non-empty string path",
        )

    target_path = (project_root / path_arg).resolve()
    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error=str(exc),
            metadata={"path": str(target_path)},
        )

    return ToolResult(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        status="ok",
        output_preview=content[:500],
        output_digest=_digest_text(content),
        metadata={
            "path": str(target_path),
            "bytes": len(content.encode("utf-8")),
            "lines": len(content.splitlines()),
        },
    )


def write_file(intent: ToolIntent, project_root: Path) -> ToolResult:
    path_arg = intent.arguments.get("path")
    content = intent.arguments.get("content")
    if not isinstance(path_arg, str) or not path_arg:
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error="write_file requires a non-empty string path",
        )
    if not isinstance(content, str):
        return ToolResult(
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            status="error",
            error="write_file requires string content",
        )

    target_path = (project_root / path_arg).resolve()
    existed = target_path.exists()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8", newline="\n")
    return ToolResult(
        run_id=intent.run_id,
        tool_call_id=intent.tool_call_id,
        tool_name=intent.tool_name,
        status="ok",
        output_preview=f"wrote {path_arg}",
        output_digest=_digest_text(content),
        metadata={
            "path": str(target_path),
            "bytes": len(content.encode("utf-8")),
            "lines": len(content.splitlines()),
            "created": not existed,
        },
    )
