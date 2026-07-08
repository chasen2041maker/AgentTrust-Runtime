"""Schema objects shared across the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now_iso() -> str:
    """Return a compact UTC timestamp suitable for trace events."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ToolIntent:
    """A normalized request for a tool execution."""

    run_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    source: str
    created_at: str = field(default_factory=utc_now_iso)
    runtime_mode: str = "interactive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "source": self.source,
            "created_at": self.created_at,
            "runtime_mode": self.runtime_mode,
        }


@dataclass(frozen=True)
class ToolResult:
    """The auditable result of a tool execution attempt."""

    run_id: str
    tool_call_id: str
    tool_name: str
    status: str
    output_preview: str = ""
    output_digest: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "output_preview": self.output_preview,
            "output_digest": self.output_digest,
            "metadata": self.metadata,
            "error": self.error,
            "created_at": self.created_at,
        }
