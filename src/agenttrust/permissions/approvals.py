"""Approval finalization rules for ask decisions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Callable

from agenttrust.domain.approvals import reviewable_arguments
from agenttrust.domain.decisions import FinalPermission, PermissionDecision


VALID_APPROVAL_MODES = frozenset({"deferred", "deny", "inline_prompt", "mock"})


def approval_mode_for_runtime(runtime_mode: str, approval_mode: str | None = None) -> str:
    """Resolve an explicit approval behavior without conflating it with runtime mode."""

    if approval_mode is None:
        return "mock" if runtime_mode == "test" else "deferred"
    if approval_mode not in VALID_APPROVAL_MODES:
        raise ValueError(f"invalid approval mode: {approval_mode}")
    if approval_mode == "mock" and runtime_mode != "test":
        raise ValueError("approval mode 'mock' is only available in test runtime mode")
    return approval_mode


def finalize_permission(
    decision: PermissionDecision,
    runtime_mode: str | None = None,
    approval_response: str | None = None,
    *,
    approval_mode: str | None = None,
) -> FinalPermission:
    resolved_mode = approval_mode or runtime_mode or "deny"
    if decision.effect in {"allow", "deny"}:
        return FinalPermission(
            effect=decision.effect,
            final_effect=decision.effect,
            reason=decision.reason,
            approval_required=False,
        )
    if resolved_mode in {"noninteractive", "deny"}:
        return FinalPermission(
            effect=decision.effect,
            final_effect="deny",
            reason="approval_required",
            approval_required=True,
        )
    if resolved_mode in {"test", "mock"}:
        return FinalPermission(
            effect=decision.effect,
            final_effect="allow",
            reason="mock_approver_approved",
            approval_required=True,
        )
    if resolved_mode in {"interactive", "inline_prompt"}:
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
    arguments: Mapping[str, object] | None = None,
    input_func: Callable[[str], str] = input,
) -> str:
    review = json.dumps(reviewable_arguments(arguments or {}), ensure_ascii=False, indent=2, sort_keys=True)
    prompt = (
        f"Approve tool call {decision.tool_call_id} "
        f"({decision.tool_name})? Reason: {decision.reason}\n"
        f"Reviewable arguments:\n{review}\n"
        "Approve [y/N]: "
    )
    answer = input_func(prompt).strip().lower()
    return "approve" if answer in {"y", "yes", "approve"} else "deny"
