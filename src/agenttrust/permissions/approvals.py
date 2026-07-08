"""Approval finalization rules for ask decisions."""

from __future__ import annotations

from dataclasses import dataclass

from agenttrust.permissions.engine import PermissionDecision


@dataclass(frozen=True)
class FinalPermission:
    effect: str
    final_effect: str
    reason: str
    approval_required: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "effect": self.effect,
            "final_effect": self.final_effect,
            "reason": self.reason,
            "approval_required": self.approval_required,
        }


def finalize_permission(decision: PermissionDecision, runtime_mode: str) -> FinalPermission:
    if decision.effect in {"allow", "deny"}:
        return FinalPermission(
            effect=decision.effect,
            final_effect=decision.effect,
            reason=decision.reason,
            approval_required=False,
        )
    if runtime_mode == "noninteractive":
        return FinalPermission(
            effect=decision.effect,
            final_effect="deny",
            reason="approval_required",
            approval_required=True,
        )
    if runtime_mode == "test":
        return FinalPermission(
            effect=decision.effect,
            final_effect="allow",
            reason="mock_approver_approved",
            approval_required=True,
        )
    return FinalPermission(
        effect=decision.effect,
        final_effect="deny",
        reason="interactive_approval_required",
        approval_required=True,
    )
