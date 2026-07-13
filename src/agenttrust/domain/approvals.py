"""Approval entities that bind a human decision to exact tool arguments."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from agenttrust.domain.models import utc_now_iso


ApprovalDecision = str
_VALID_DECISIONS = frozenset({"pending", "approved", "denied"})


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
        if self.expires_at is not None:
            _require_text("expires_at", self.expires_at)
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
        expires_at: str | None = None,
        requested_at: str | None = None,
    ) -> ApprovalRequest:
        return cls(
            approval_id=f"approval_{uuid4().hex}",
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_digest=arguments_digest,
            reason=reason,
            policy_rule_id=policy_rule_id,
            expires_at=expires_at,
            requested_at=requested_at or utc_now_iso(),
        )

    @property
    def is_pending(self) -> bool:
        return self.decision == "pending"

    def approve(self, approver_id: str, decision_reason: str, decided_at: str | None = None) -> ApprovalRequest:
        return self._decide("approved", approver_id, decision_reason, decided_at)

    def deny(self, approver_id: str, decision_reason: str, decided_at: str | None = None) -> ApprovalRequest:
        return self._decide("denied", approver_id, decision_reason, decided_at)

    def _decide(
        self,
        decision: ApprovalDecision,
        approver_id: str,
        decision_reason: str,
        decided_at: str | None,
    ) -> ApprovalRequest:
        if not self.is_pending:
            raise ValueError(f"approval {self.approval_id} has already been decided")
        return replace(
            self,
            decision=decision,
            approver_id=approver_id,
            decision_reason=decision_reason,
            decided_at=decided_at or utc_now_iso(),
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments_digest": self.arguments_digest,
            "policy_rule_id": self.policy_rule_id,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "expires_at": self.expires_at,
            "decision": self.decision,
            "approver_id": self.approver_id,
            "decision_reason": self.decision_reason,
            "decided_at": self.decided_at,
        }
