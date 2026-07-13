"""Approval finalization rules for ask decisions."""

from __future__ import annotations

from typing import Callable

from agenttrust.domain.decisions import FinalPermission, PermissionDecision


def finalize_permission(
    decision: PermissionDecision,
    runtime_mode: str,
    approval_response: str | None = None,
) -> FinalPermission:
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
    if runtime_mode == "interactive":
        if approval_response == "approve":
            return FinalPermission(
                effect=decision.effect,
                final_effect="allow",
                reason="interactive_approved",
                approval_required=True,
            )
        if approval_response == "deny":
            return FinalPermission(
                effect=decision.effect,
                final_effect="deny",
                reason="interactive_denied",
                approval_required=True,
            )
        return FinalPermission(
            effect=decision.effect,
            final_effect="ask",
            reason="interactive_approval_required",
            approval_required=True,
        )
    return FinalPermission(
        effect=decision.effect,
        final_effect="deny",
        reason="interactive_approval_required",
        approval_required=True,
    )


def request_interactive_approval(
    decision: PermissionDecision,
    input_func: Callable[[str], str] = input,
) -> str:
    prompt = (
        f"Approve tool call {decision.tool_call_id} "
        f"({decision.tool_name})? Reason: {decision.reason} [y/N]: "
    )
    answer = input_func(prompt).strip().lower()
    return "approve" if answer in {"y", "yes", "approve"} else "deny"
