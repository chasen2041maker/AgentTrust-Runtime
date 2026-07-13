"""Architecture tests that protect the first domain extraction seam."""

from __future__ import annotations

import ast
from pathlib import Path

from agenttrust.domain import decisions, models, policy
from agenttrust.domain.decisions import FinalPermission, HookDecision, PermissionDecision, SandboxDecision
from agenttrust.domain.models import ToolIntent, ToolResult, utc_now_iso
from agenttrust.domain.policy import HookRule, Policy, PolicyRule
from agenttrust.permissions.approvals import FinalPermission as LegacyFinalPermission
from agenttrust.permissions.engine import PermissionDecision as LegacyPermissionDecision
from agenttrust.permissions.hooks import HookDecision as LegacyHookDecision
from agenttrust.permissions.hooks import HookRule as LegacyHookRule
from agenttrust.permissions.policy import Policy as LegacyPolicy
from agenttrust.permissions.policy import PolicyRule as LegacyPolicyRule
from agenttrust.permissions.sandbox import SandboxDecision as LegacySandboxDecision
from agenttrust.schemas import ToolIntent as LegacyToolIntent
from agenttrust.schemas import ToolResult as LegacyToolResult
from agenttrust.schemas import utc_now_iso as legacy_utc_now_iso


DOMAIN_DIR = Path(__file__).parents[1] / "src" / "agenttrust" / "domain"
APPLICATION_DIR = Path(__file__).parents[1] / "src" / "agenttrust" / "application"
ALLOWED_IMPORT_ROOTS = {"__future__", "dataclasses", "datetime", "fnmatch", "typing", "agenttrust"}
APPLICATION_ALLOWED_IMPORT_ROOTS = {"__future__", "dataclasses", "pathlib", "typing", "agenttrust"}


def _import_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_domain_imports_only_standard_library_or_domain_modules() -> None:
    for module_path in DOMAIN_DIR.glob("*.py"):
        roots = _import_roots(module_path.read_text(encoding="utf-8"))
        assert roots <= ALLOWED_IMPORT_ROOTS, module_path.name


def test_domain_has_no_infrastructure_or_interface_imports() -> None:
    forbidden = (
        "agenttrust.adapters",
        "agenttrust.application",
        "agenttrust.cli",
        "agenttrust.groundguard_adapter",
        "agenttrust.permissions",
        "agenttrust.runtime",
        "agenttrust.tools",
        "yaml",
        "subprocess",
        "pathlib",
        "os",
    )
    for module_path in DOMAIN_DIR.glob("*.py"):
        source = module_path.read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden), module_path.name


def test_application_imports_only_standard_library_domain_and_ports() -> None:
    for module_path in APPLICATION_DIR.glob("*.py"):
        roots = _import_roots(module_path.read_text(encoding="utf-8"))
        assert roots <= APPLICATION_ALLOWED_IMPORT_ROOTS, module_path.name


def test_application_has_no_concrete_adapter_imports() -> None:
    forbidden = (
        "agenttrust.adapters",
        "agenttrust.cli",
        "agenttrust.context_lite",
        "agenttrust.groundguard_adapter",
        "agenttrust.memory_lite",
        "agenttrust.permissions",
        "agenttrust.runtime",
        "agenttrust.skills_lite",
        "agenttrust.tools",
        "yaml",
        "subprocess",
    )
    for module_path in APPLICATION_DIR.glob("*.py"):
        source = module_path.read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden), module_path.name


def test_legacy_model_imports_reexport_domain_objects() -> None:
    assert LegacyToolIntent is ToolIntent
    assert LegacyToolResult is ToolResult
    assert legacy_utc_now_iso is utc_now_iso
    assert models.ToolIntent is ToolIntent


def test_legacy_decision_and_policy_imports_reexport_domain_objects() -> None:
    assert LegacyFinalPermission is FinalPermission
    assert LegacyHookDecision is HookDecision
    assert LegacyPermissionDecision is PermissionDecision
    assert LegacySandboxDecision is SandboxDecision
    assert LegacyHookRule is HookRule
    assert LegacyPolicy is Policy
    assert LegacyPolicyRule is PolicyRule
    assert decisions.PermissionDecision is PermissionDecision
    assert policy.PolicyRule is PolicyRule
