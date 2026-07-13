"""Application use case for one governed tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agenttrust.application.ports import (
    EvidenceRecord,
    EvidenceRecorderPort,
    FactMapperPort,
    FactStorePort,
    PolicyEvaluatorPort,
    RecoveryCheckpointPort,
    SandboxPort,
    ToolExecutorPort,
)
from agenttrust.domain.decisions import FinalPermission, HookDecision, PermissionDecision, SandboxDecision
from agenttrust.domain.lifecycle import ToolCallStatus
from agenttrust.domain.models import ToolIntent, ToolResult
from agenttrust.domain.policy import HookRule


PermissionFinalizer = Callable[[PermissionDecision, str, str | None], FinalPermission]
HookEvaluator = Callable[[ToolIntent, tuple[HookRule, ...]], HookDecision]
ApprovalRequester = Callable[[PermissionDecision], str]
ToolStatusObserver = Callable[[ToolCallStatus], None]


@dataclass(frozen=True)
class ToolRunOutcome:
    """Evidence-bearing outcome for one governed tool execution."""

    intent: ToolIntent
    permission_decision: PermissionDecision
    final_permission: FinalPermission
    hook_decision: HookDecision
    sandbox_decision: SandboxDecision | None
    result: ToolResult | None
    facts: tuple[EvidenceRecord, ...]


class RunToolUseCase:
    """Execute policy, approval, sandbox, recovery, tool, and fact stages."""

    def __init__(
        self,
        *,
        evidence: EvidenceRecorderPort,
        policy_evaluator: PolicyEvaluatorPort,
        sandbox: SandboxPort,
        tool_executor: ToolExecutorPort,
        finalize_permission: PermissionFinalizer,
        evaluate_hooks: HookEvaluator,
        request_approval: ApprovalRequester | None = None,
        create_recovery_checkpoint: RecoveryCheckpointPort | None = None,
        map_facts: FactMapperPort | None = None,
        store_facts: FactStorePort | None = None,
    ) -> None:
        self._evidence = evidence
        self._policy_evaluator = policy_evaluator
        self._sandbox = sandbox
        self._tool_executor = tool_executor
        self._finalize_permission = finalize_permission
        self._evaluate_hooks = evaluate_hooks
        self._request_approval = request_approval
        self._create_recovery_checkpoint = create_recovery_checkpoint
        self._map_facts = map_facts
        self._store_facts = store_facts

    def execute(
        self,
        intent: ToolIntent,
        *,
        project_root: Path,
        run_dir: Path,
        runtime_mode: str,
        hooks: tuple[HookRule, ...] = (),
        facts_path: Path | None = None,
        on_tool_call_status: ToolStatusObserver | None = None,
        defer_approval: bool = False,
        approval_response: str | None = None,
    ) -> ToolRunOutcome:
        self._evidence.append("tool_intent", **intent.to_dict())
        permission_decision = self._policy_evaluator.decide(intent)
        hook_decision = self._evaluate_hooks(intent, hooks)
        if hook_decision.hook_id is not None:
            self._evidence.append("hook_decision", **hook_decision.to_dict())

        if permission_decision.effect == "ask" and approval_response is None and on_tool_call_status is not None:
            on_tool_call_status("waiting_approval")
        if (
            permission_decision.effect == "ask"
            and approval_response is None
            and runtime_mode == "interactive"
            and hook_decision.effect != "deny"
            and self._request_approval is not None
        ):
            self._evidence.append(
                "approval_request",
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                reason=permission_decision.reason,
            )
            approval_response = self._request_approval(permission_decision)

        if (
            permission_decision.effect == "ask"
            and approval_response is None
            and defer_approval
            and hook_decision.effect != "deny"
        ):
            final_permission = FinalPermission(
                effect=permission_decision.effect,
                final_effect="ask",
                reason="approval_pending",
                approval_required=True,
            )
        elif approval_response is not None:
            final_permission = self._finalize_permission(permission_decision, "interactive", approval_response)
        else:
            final_permission = self._finalize_permission(permission_decision, runtime_mode, approval_response)
        if hook_decision.effect == "deny" and final_permission.final_effect != "deny":
            final_permission = FinalPermission(
                effect=final_permission.effect,
                final_effect="deny",
                reason=hook_decision.reason,
                approval_required=final_permission.approval_required,
            )
        permission_event = {
            **permission_decision.to_dict(),
            **final_permission.to_dict(),
            "runtime_mode": runtime_mode,
        }
        self._evidence.append("permission_decision", **permission_event)
        if final_permission.final_effect != "allow":
            if final_permission.final_effect != "ask" and on_tool_call_status is not None:
                on_tool_call_status("policy_denied")
            return ToolRunOutcome(
                intent=intent,
                permission_decision=permission_decision,
                final_permission=final_permission,
                hook_decision=hook_decision,
                sandbox_decision=None,
                result=None,
                facts=(),
            )

        if permission_decision.effect == "ask" and on_tool_call_status is not None:
            on_tool_call_status("approved")

        sandbox_decision = self._sandbox.check(intent)
        self._evidence.append("sandbox_decision", **sandbox_decision.to_dict())
        if sandbox_decision.effect != "allow":
            if on_tool_call_status is not None:
                on_tool_call_status("sandbox_denied")
            return ToolRunOutcome(
                intent=intent,
                permission_decision=permission_decision,
                final_permission=final_permission,
                hook_decision=hook_decision,
                sandbox_decision=sandbox_decision,
                result=None,
                facts=(),
            )

        if self._create_recovery_checkpoint is not None:
            backup_record = self._create_recovery_checkpoint(intent, project_root, run_dir)
            if backup_record is not None:
                self._evidence.append("backup_created", **backup_record.to_dict())

        if on_tool_call_status is not None:
            on_tool_call_status("executing")
        try:
            result = self._tool_executor.execute(intent, project_root)
        except Exception:
            if on_tool_call_status is not None:
                on_tool_call_status("failed")
            raise
        self._evidence.append("tool_result", **result.to_dict())
        if on_tool_call_status is not None:
            on_tool_call_status("succeeded" if result.status == "ok" else "failed")
        facts = tuple(self._map_facts(result)) if self._map_facts is not None else ()
        if facts and facts_path is not None and self._store_facts is not None:
            self._store_facts(facts_path, facts)
        self._evidence.append(
            "fact_mapped",
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            tool_name=intent.tool_name,
            fact_count=len(facts),
            facts=[fact.to_dict() for fact in facts],
        )
        return ToolRunOutcome(
            intent=intent,
            permission_decision=permission_decision,
            final_permission=final_permission,
            hook_decision=hook_decision,
            sandbox_decision=sandbox_decision,
            result=result,
            facts=facts,
        )
