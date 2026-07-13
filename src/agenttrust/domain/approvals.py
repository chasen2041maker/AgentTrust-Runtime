"""Approval entities that bind a human decision to exact tool arguments."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Mapping
from uuid import uuid4

from agenttrust.domain.models import utc_now_iso


ApprovalDecision = str
_VALID_DECISIONS = frozenset({"pending", "approved", "denied"})
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|pass(?:word|phrase)?|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(api[_-]?(?:key|token)|authorization|cookie|password|secret|token)\s*([=:])\s*[^\s,;]+"
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_PREVIEW_LIMIT = 240


def _require_text(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending or decided approval, bound to one Tool Call arguments digest."""

    approval_id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str
    reason: str
    requested_at: str
    arguments_preview: Mapping[str, object] = field(default_factory=dict)
    policy_rule_id: str | None = None
    expires_at: str | None = None
    decision: ApprovalDecision = "pending"
    approver_id: str | None = None
    decision_reason: str | None = None
    decided_at: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("approval_id", self.approval_id),
            ("run_id", self.run_id),
            ("tool_call_id", self.tool_call_id),
            ("tool_name", self.tool_name),
            ("arguments_digest", self.arguments_digest),
            ("reason", self.reason),
            ("requested_at", self.requested_at),
        ):
            _require_text(field_name, value)
        if self.policy_rule_id is not None:
            _require_text("policy_rule_id", self.policy_rule_id)
        if not isinstance(self.arguments_preview, Mapping) or not all(
            isinstance(key, str) for key in self.arguments_preview
        ):
            raise ValueError("approval arguments_preview must be a string-keyed mapping")
        try:
            json.dumps(self.arguments_preview, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("approval arguments_preview must be JSON serializable") from exc
        if self.expires_at is not None:
            _require_text("expires_at", self.expires_at)
            _parse_timestamp(self.expires_at)
        if self.decision not in _VALID_DECISIONS:
            raise ValueError(f"invalid approval decision: {self.decision}")
        if self.decision == "pending":
            if any(value is not None for value in (self.approver_id, self.decision_reason, self.decided_at)):
                raise ValueError("pending approval must not include a decision")
        else:
            if self.approver_id is None or self.decision_reason is None or self.decided_at is None:
                raise ValueError("decided approval requires approver_id, decision_reason, and decided_at")
            _require_text("approver_id", self.approver_id)
            _require_text("decision_reason", self.decision_reason)
            _require_text("decided_at", self.decided_at)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        reason: str,
        policy_rule_id: str | None = None,
        arguments_preview: Mapping[str, object] | None = None,
        expires_at: str | None = None,
        ttl_seconds: int | None = None,
        requested_at: str | None = None,
    ) -> ApprovalRequest:
        if ttl_seconds is not None and (
            isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0
        ):
            raise ValueError("approval ttl_seconds must be a positive integer")
        if ttl_seconds is not None and expires_at is not None:
            raise ValueError("approval expires_at and ttl_seconds are mutually exclusive")
        timestamp = requested_at or utc_now_iso()
        if ttl_seconds is not None:
            expires_at = (_parse_timestamp(timestamp) + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
        return cls(
            approval_id=f"approval_{uuid4().hex}",
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_digest=arguments_digest,
            reason=reason,
            policy_rule_id=policy_rule_id,
            arguments_preview=dict(arguments_preview or {}),
            expires_at=expires_at,
            requested_at=timestamp,
        )

    @property
    def is_pending(self) -> bool:
        return self.decision == "pending"

    def is_expired(self, at: str | None = None) -> bool:
        """Return whether this request is no longer actionable at the given time."""

        return self.expires_at is not None and _parse_timestamp(self.expires_at) <= _parse_timestamp(at or utc_now_iso())

    def approve(self, approver_id: str, decision_reason: str, decided_at: str | None = None) -> ApprovalRequest:
        return self._decide("approved", approver_id, decision_reason, decided_at)

    def deny(self, approver_id: str, decision_reason: str, decided_at: str | None = None) -> ApprovalRequest:
        return self._decide("denied", approver_id, decision_reason, decided_at)

    def expire(self, actor_id: str, decided_at: str | None = None) -> ApprovalRequest:
        """Record a pending request as denied because its validity window elapsed."""

        timestamp = decided_at or utc_now_iso()
        if not self.is_expired(timestamp):
            raise ValueError(f"approval {self.approval_id} has not expired")
        return self._decide("denied", actor_id, "approval_expired", timestamp, enforce_expiry=False)

    def _decide(
        self,
        decision: ApprovalDecision,
        approver_id: str,
        decision_reason: str,
        decided_at: str | None,
        enforce_expiry: bool = True,
    ) -> ApprovalRequest:
        if not self.is_pending:
            raise ValueError(f"approval {self.approval_id} has already been decided")
        timestamp = decided_at or utc_now_iso()
        if enforce_expiry and self.is_expired(timestamp):
            raise ValueError(f"approval {self.approval_id} has expired")
        return replace(
            self,
            decision=decision,
            approver_id=approver_id,
            decision_reason=decision_reason,
            decided_at=timestamp,
        )

    def to_dict(self) -> dict[str, object | None]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments_digest": self.arguments_digest,
            "arguments": dict(self.arguments_preview),
            "policy_rule_id": self.policy_rule_id,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "expires_at": self.expires_at,
            "decision": self.decision,
            "approver_id": self.approver_id,
            "decision_reason": self.decision_reason,
            "decided_at": self.decided_at,
        }


def reviewable_arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    """Create a bounded, redacted approval view without changing its digest binding."""

    return _review_mapping(arguments)


def _review_mapping(raw: Mapping[str, object]) -> dict[str, object]:
    review: dict[str, object] = {}
    for key, value in raw.items():
        if _SENSITIVE_KEY_PATTERN.search(key):
            review[key] = "[REDACTED]"
        elif key == "content" and isinstance(value, str):
            review["content_bytes"] = len(value.encode("utf-8"))
            review["content_sha256"] = "sha256:" + sha256(value.encode("utf-8")).hexdigest()
            review["content_preview"] = _preview_text(value)
        else:
            review[key] = _review_value(value)
    return review


def _review_value(value: object) -> object:
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return _review_mapping(value)
    if isinstance(value, list):
        return [_review_value(item) for item in value]
    if isinstance(value, tuple):
        return [_review_value(item) for item in value]
    if isinstance(value, str):
        return _preview_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return f"<{type(value).__name__}>"


def _preview_text(value: str) -> str:
    redacted = _SENSITIVE_TEXT_PATTERN.sub(r"\1\2[REDACTED]", value)
    redacted = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", redacted)
    return redacted if len(redacted) <= _PREVIEW_LIMIT else redacted[:_PREVIEW_LIMIT] + "..."


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid approval timestamp: {value}") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"approval timestamp must include a timezone: {value}")
    return timestamp
