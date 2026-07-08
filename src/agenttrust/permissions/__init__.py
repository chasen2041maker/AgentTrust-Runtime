"""Permission and sandbox controls."""

from agenttrust.permissions.approvals import finalize_permission, request_interactive_approval
from agenttrust.permissions.engine import PermissionDecision, PermissionEngine
from agenttrust.permissions.hooks import HookDecision, HookRule, evaluate_pre_tool_hooks
from agenttrust.permissions.policy import Policy, PolicyRule, load_policy
from agenttrust.permissions.sandbox import PathSandbox, SandboxDecision

__all__ = [
    "PathSandbox",
    "HookDecision",
    "HookRule",
    "PermissionDecision",
    "PermissionEngine",
    "Policy",
    "PolicyRule",
    "SandboxDecision",
    "evaluate_pre_tool_hooks",
    "finalize_permission",
    "load_policy",
    "request_interactive_approval",
]
