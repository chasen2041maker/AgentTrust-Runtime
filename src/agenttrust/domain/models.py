"""Core execution models with no infrastructure dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any


def utc_now_iso() -> str:
    """Return a compact UTC timestamp suitable for evidence events."""
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


@dataclass(frozen=True)
class EvidenceEvent:
    """A canonical, identity-aware execution evidence record."""

    run_id: str
    stage: str
    actor_id: str = "local-user"
    agent_id: str | None = None
    session_id: str | None = None
    tool_call_id: str | None = None
    policy_version: str | None = None
    risk_tags: tuple[str, ...] = ()
    input_digest: str | None = None
    output_digest: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "actor_id": self.actor_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "policy_version": self.policy_version,
            "risk_tags": list(self.risk_tags),
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "created_at": self.created_at,
        }

    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()
