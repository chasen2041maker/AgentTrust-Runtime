"""Command line interface for AgentTrust Runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agenttrust.context_lite import build_context_pack, export_context_to_run
from agenttrust.mcp_lite import grant_mcp_consent, inspect_mcp_config, trust_mcp_server
from agenttrust.memory_lite import add_memory, clear_memory, list_memory
from agenttrust.adapters.policy.yaml_policy import DEFAULT_POLICY_TEXT, load_policy
from agenttrust.runtime.fixtures import list_fixtures, run_fixture
from agenttrust.runtime.live import run_live
from agenttrust.runtime.recovery import restore_run
from agenttrust.runtime.report import resolve_run_dir, timeline_lines, write_html_report, write_markdown_report
from agenttrust.runtime.trace import verify_trace
from agenttrust.adapters.evidence.export import export_ndjson
from agenttrust.interfaces.python_api import AgentTrustRuntime
from agenttrust.adapters.evidence.approval_journal import JsonlApprovalJournal
from agenttrust.adapters.evidence.jsonl_store import TraceRecorder
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.sqlite_state import SQLiteStateProjection
from agenttrust.adapters.evidence.sqlite_state import rebuild_state_from_traces
from agenttrust.skills_lite import ensure_demo_skill, list_skills, load_skill
from agenttrust.tools.registry import get_tool_spec, list_tool_specs
from agenttrust.domain.approvals import ApprovalRequest


def _project_root(path: str | None) -> Path:
    return Path(path).resolve() if path else Path.cwd().resolve()


def init_project(project_root: Path) -> Path:
    agenttrust_dir = project_root / ".agenttrust"
    runs_dir = agenttrust_dir / "runs"
    policy_path = agenttrust_dir / "policy.yaml"
    runs_dir.mkdir(parents=True, exist_ok=True)
    if not policy_path.exists():
        policy_path.write_text(DEFAULT_POLICY_TEXT, encoding="utf-8")
    ensure_demo_skill(project_root)
    return agenttrust_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenttrust")
    parser.add_argument("--project-root", help="Project root. Defaults to the current directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize .agenttrust project metadata.")

    fixtures_parser = subparsers.add_parser("fixtures", help="List built-in fixtures.")
    fixtures_parser.set_defaults(command="fixtures")

    run_parser = subparsers.add_parser("run", help="Run a simple task, optionally with a local skill.")
    run_parser.add_argument("task", nargs="?", default="")
    run_parser.add_argument("run_id", nargs="?")
    run_parser.add_argument("--skill")

    run_fixture_parser = subparsers.add_parser("run-fixture", help="Run a deterministic fixture.")
    run_fixture_parser.add_argument("name", help="Fixture name.")
    run_fixture_parser.add_argument("--non-interactive", action="store_true", help="Run in noninteractive mode.")
    run_fixture_parser.add_argument("--mode", choices=["interactive", "noninteractive", "test"], help="Runtime mode.")

    run_live_parser = subparsers.add_parser("run-live", help="Run the minimal live adapter.")
    run_live_parser.add_argument("name", help="Live adapter request name.")
    run_live_parser.add_argument("--mode", choices=["interactive", "noninteractive", "test"], default="interactive")

    replay_parser = subparsers.add_parser("replay", help="Print a run timeline.")
    replay_parser.add_argument("run_id")

    report_parser = subparsers.add_parser("report", help="Generate a minimal markdown report.")
    report_parser.add_argument("run_id")
    report_parser.add_argument("--format", choices=["markdown", "html"], default="markdown")

    restore_parser = subparsers.add_parser("restore", help="Restore write_file changes from a run.")
    restore_parser.add_argument("run_id")
    restore_parser.add_argument("--file")
    restore_parser.add_argument("--dry-run", action="store_true")

    evidence_parser = subparsers.add_parser("evidence", help="Evidence integrity helpers.")
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_command", required=True)
    evidence_verify = evidence_subparsers.add_parser("verify", help="Verify a run evidence hash chain.")
    evidence_verify.add_argument("run_id")
    evidence_export = evidence_subparsers.add_parser("export", help="Export run evidence as NDJSON.")
    evidence_export.add_argument("run_id")

    state_parser = subparsers.add_parser("state", help="Derived SQLite state helpers.")
    state_subparsers = state_parser.add_subparsers(dest="state_command", required=True)
    state_subparsers.add_parser("rebuild", help="Rebuild state.db from verified JSONL evidence.")

    approvals_parser = subparsers.add_parser("approvals", help="Persisted approval request helpers.")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command", required=True)
    approvals_subparsers.add_parser("list", help="List approval requests.")
    approval_inspect = approvals_subparsers.add_parser("inspect", help="Inspect one approval request.")
    approval_inspect.add_argument("approval_id")
    for command, help_text in (("approve", "Approve a pending request."), ("deny", "Deny a pending request.")):
        decision_parser = approvals_subparsers.add_parser(command, help=help_text)
        decision_parser.add_argument("approval_id")
        decision_parser.add_argument("--reason", required=True)
        decision_parser.add_argument("--approver")

    policy_parser = subparsers.add_parser("policy", help="Policy helpers.")
    policy_subparsers = policy_parser.add_subparsers(dest="policy_command", required=True)
    validate_parser = policy_subparsers.add_parser("validate", help="Validate that a policy file exists.")
    validate_parser.add_argument("path")

    tools_parser = subparsers.add_parser("tools", help="Tool registry helpers.")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command", required=True)
    tools_subparsers.add_parser("list", help="List tools.")
    tool_inspect = tools_subparsers.add_parser("inspect", help="Inspect one tool.")
    tool_inspect.add_argument("name")

    mcp_parser = subparsers.add_parser("mcp", help="MCP Lite helpers.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_inspect = mcp_subparsers.add_parser("inspect", help="Inspect an MCP config.")
    mcp_inspect.add_argument("path")
    mcp_consent = mcp_subparsers.add_parser("consent", help="Grant consent for a local MCP server.")
    mcp_consent.add_argument("server")
    mcp_trust = mcp_subparsers.add_parser("trust", help="Trust an MCP server tool.")
    mcp_trust.add_argument("server")
    mcp_trust.add_argument("--tool", action="append", required=True)
    mcp_trust.add_argument("--sandbox-profile", choices=["strict", "standard"], default="strict")

    skills_parser = subparsers.add_parser("skills", help="Skill Lite helpers.")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_subparsers.add_parser("list", help="List local skills.")
    skill_inspect = skills_subparsers.add_parser("inspect", help="Inspect a local skill.")
    skill_inspect.add_argument("name")

    hooks_parser = subparsers.add_parser("hooks", help="Hook Lite helpers.")
    hooks_subparsers = hooks_parser.add_subparsers(dest="hooks_command", required=True)
    hooks_subparsers.add_parser("list", help="List configured pre_tool hooks.")

    memory_parser = subparsers.add_parser("memory", help="Memory Lite helpers.")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_subparsers.add_parser("list", help="List memory entries.")
    memory_add = memory_subparsers.add_parser("add", help="Add memory.")
    memory_add.add_argument("scope", choices=["project", "decision", "run"])
    memory_add.add_argument("text")
    memory_subparsers.add_parser("inspect", help="Inspect memory as JSON.")
    memory_clear = memory_subparsers.add_parser("clear", help="Clear memory scope.")
    memory_clear.add_argument("--scope", choices=["project", "decision", "run", "all"], default="run")

    context_parser = subparsers.add_parser("context", help="Context Lite helpers.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    context_build = context_subparsers.add_parser("build", help="Build a deterministic context pack.")
    context_build.add_argument("--skill")
    context_build.add_argument("--budget", type=int, default=4000)
    context_preview = context_subparsers.add_parser("preview", help="Print a deterministic context pack.")
    context_preview.add_argument("--skill")
    context_preview.add_argument("--budget", type=int, default=4000)
    context_export = context_subparsers.add_parser("export", help="Copy context pack into a run artifact.")
    context_export.add_argument("--run", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = _project_root(args.project_root)

    if args.command == "init":
        agenttrust_dir = init_project(project_root)
        print(f"Initialized {agenttrust_dir}")
        return 0

    if args.command == "fixtures":
        for fixture_name in list_fixtures():
            print(fixture_name)
        return 0

    if args.command == "run":
        init_project(project_root)
        if args.task in {"resume", "cancel"}:
            if not args.run_id:
                print(f"run {args.task} requires a run_id", file=sys.stderr)
                return 2
            try:
                runtime = AgentTrustRuntime(project_root)
                if args.task == "resume":
                    with runtime.resume(args.run_id) as resumed_session:
                        outcome = resumed_session.resume_pending_approval()
                    print(
                        json.dumps(
                            {
                                "run_id": resumed_session.run_id,
                                "session_status": resumed_session.session.status,
                                "tool_call_id": outcome.tool_call.tool_call_id,
                                "tool_call_status": outcome.tool_call.status,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                else:
                    cancelled = runtime.cancel(args.run_id)
                    print(json.dumps(cancelled.to_dict(), ensure_ascii=False, indent=2))
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"run {args.task} failed: {exc}", file=sys.stderr)
                return 2
            return 0
        if args.skill:
            try:
                load_skill(project_root, args.skill)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            result = run_fixture(
                "skill_code_review",
                project_root=project_root,
                runtime_mode="test",
                skill_override=args.skill,
            )
            print(f"run_id={result.run_id}")
            print(f"run_dir={result.run_dir}")
            return 0
        print("plain run requires --skill in this Lite implementation", file=sys.stderr)
        return 2

    if args.command == "run-fixture":
        init_project(project_root)
        runtime_mode = args.mode or ("noninteractive" if args.non_interactive else "interactive")
        try:
            result = run_fixture(args.name, project_root=project_root, runtime_mode=runtime_mode)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"run_id={result.run_id}")
        print(f"run_dir={result.run_dir}")
        return 0

    if args.command == "run-live":
        init_project(project_root)
        try:
            result = run_live(args.name, project_root=project_root, runtime_mode=args.mode)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"run_id={result.run_id}")
        print(f"run_dir={result.run_dir}")
        return 0

    if args.command == "replay":
        run_dir = resolve_run_dir(project_root, args.run_id)
        for line in timeline_lines(run_dir):
            print(line)
        return 0

    if args.command == "report":
        if args.format == "html":
            report_path = write_html_report(resolve_run_dir(project_root, args.run_id))
        else:
            report_path = write_markdown_report(resolve_run_dir(project_root, args.run_id))
        print(report_path)
        return 0

    if args.command == "restore":
        actions = restore_run(resolve_run_dir(project_root, args.run_id), only_file=args.file, dry_run=args.dry_run)
        print(json.dumps(actions, ensure_ascii=False, indent=2))
        return 0

    if args.command == "evidence" and args.evidence_command == "verify":
        verification_result = verify_trace(resolve_run_dir(project_root, args.run_id) / "trace.jsonl")
        print(json.dumps(verification_result, ensure_ascii=False, indent=2))
        return 0 if verification_result["valid"] else 2

    if args.command == "evidence" and args.evidence_command == "export":
        print(export_ndjson(resolve_run_dir(project_root, args.run_id)))
        return 0

    if args.command == "state" and args.state_command == "rebuild":
        try:
            state_result = rebuild_state_from_traces(project_root)
        except (OSError, ValueError) as exc:
            print(f"state rebuild failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(state_result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "approvals":
        state = SQLiteStateProjection(project_root)
        if args.approvals_command == "list":
            print(json.dumps(state.list_approvals(), ensure_ascii=False, indent=2))
            return 0
        if args.approvals_command == "inspect":
            approval = state.get_approval(args.approval_id)
            if approval is None:
                print(f"approval not found: {args.approval_id}", file=sys.stderr)
                return 2
            print(json.dumps(approval, ensure_ascii=False, indent=2))
            return 0
        approval = state.get_approval(args.approval_id)
        if approval is None:
            print(f"approval not found: {args.approval_id}", file=sys.stderr)
            return 2
        try:
            decided = _decide_approval(
                project_root,
                state,
                approval,
                decision=args.approvals_command,
                approver_id=args.approver or os.environ.get("AGENTTRUST_ACTOR_ID", "local-user"),
                reason=args.reason,
            )
        except (OSError, ValueError) as exc:
            print(f"approval decision failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(decided.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "policy" and args.policy_command == "validate":
        policy_path = (project_root / args.path).resolve()
        if not policy_path.exists():
            print(f"policy file not found: {policy_path}", file=sys.stderr)
            return 2
        try:
            load_policy(policy_path)
        except OSError:
            print(f"policy file not found: {policy_path}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"invalid policy file: {policy_path}", file=sys.stderr)
            if isinstance(exc, ValueError):
                print(str(exc), file=sys.stderr)
            return 2
        print(f"valid policy file: {policy_path}")
        return 0

    if args.command == "tools":
        if args.tools_command == "list":
            for spec in list_tool_specs():
                print(f"{spec.name}\t{spec.category}\t{spec.source}\t{spec.default_effect}")
            return 0
        if args.tools_command == "inspect":
            try:
                spec = get_tool_spec(args.name)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0

    if args.command == "mcp" and args.mcp_command == "inspect":
        try:
            payload = inspect_mcp_config((project_root / args.path).resolve())
        except (OSError, ValueError) as exc:
            print(f"invalid MCP config: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "mcp" and args.mcp_command == "consent":
        print(grant_mcp_consent(project_root, args.server))
        return 0

    if args.command == "mcp" and args.mcp_command == "trust":
        print(trust_mcp_server(project_root, args.server, args.tool, args.sandbox_profile))
        return 0

    if args.command == "skills":
        init_project(project_root)
        if args.skills_command == "list":
            for name in list_skills(project_root):
                print(name)
            return 0
        if args.skills_command == "inspect":
            try:
                skill = load_skill(project_root, args.name)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2))
            return 0

    if args.command == "hooks" and args.hooks_command == "list":
        policy = load_policy(project_root / ".agenttrust" / "policy.yaml")
        for hook in policy.hooks:
            print(f"{hook.id}\t{hook.tool}\t{hook.action}\t{hook.reason}")
        return 0

    if args.command == "memory":
        init_project(project_root)
        if args.memory_command == "list":
            memory = list_memory(project_root)
            print(memory.get("project", ""), end="")
            decisions = memory.get("decisions")
            if isinstance(decisions, list):
                for decision in decisions:
                    if isinstance(decision, dict):
                        print(f"- {decision.get('text', '')}")
            return 0
        if args.memory_command == "inspect":
            print(json.dumps(list_memory(project_root), ensure_ascii=False, indent=2))
            return 0
        if args.memory_command == "add":
            print(add_memory(project_root, args.scope, args.text))
            return 0
        if args.memory_command == "clear":
            clear_memory(project_root, args.scope)
            print(f"cleared {args.scope}")
            return 0

    if args.command == "context":
        init_project(project_root)
        if args.context_command in {"build", "preview"}:
            try:
                pack_path, manifest_path = build_context_pack(project_root, skill=args.skill, budget=args.budget)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            if args.context_command == "preview":
                print(pack_path.read_text(encoding="utf-8"))
            else:
                print(pack_path)
                print(manifest_path)
            return 0
        if args.context_command == "export":
            try:
                pack_path, manifest_path = export_context_to_run(project_root, args.run)
            except OSError as exc:
                print(f"context export failed: {exc}", file=sys.stderr)
                return 2
            print(pack_path)
            print(manifest_path)
            return 0

    parser.error("unknown command")
    return 2


def _decide_approval(
    project_root: Path,
    state: SQLiteStateProjection,
    raw_approval: dict[str, object],
    *,
    decision: str,
    approver_id: str,
    reason: str,
) -> ApprovalRequest:
    approval = _approval_from_state(raw_approval)
    if not approval.is_pending:
        raise ValueError(f"approval {approval.approval_id} has already been decided")
    run_dir = resolve_run_dir(project_root, approval.run_id)
    verification = verify_trace(run_dir / "trace.jsonl")
    if verification["valid"] is not True:
        raise ValueError("approval source trace failed hash-chain verification")
    session = state.get_session(approval.run_id)
    if session is None:
        raise ValueError(f"approval {approval.approval_id} has no persisted session")
    recorder = TraceRecorder(run_dir)
    recorder.bind(
        actor_id=_state_text(session, "actor_id"),
        agent_id=_state_optional_text(session, "agent_id"),
        session_id=_state_text(session, "session_id"),
        policy_version=_state_optional_text(session, "policy_version"),
    )
    if decision == "approve":
        decided = approval.approve(approver_id, reason)
    elif decision == "deny":
        decided = approval.deny(approver_id, reason)
    else:
        raise ValueError(f"unknown approval decision: {decision}")
    evidence = ProjectingTraceRecorder(recorder, state)
    event = evidence.append("approval_decided", **decided.to_dict())
    JsonlApprovalJournal(run_dir).append(event)
    return decided


def _approval_from_state(raw: dict[str, object]) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=_state_text(raw, "approval_id"),
        run_id=_state_text(raw, "run_id"),
        tool_call_id=_state_text(raw, "tool_call_id"),
        tool_name=_state_text(raw, "tool_name"),
        arguments_digest=_state_text(raw, "arguments_digest"),
        policy_rule_id=_state_optional_text(raw, "policy_rule_id"),
        reason=_state_text(raw, "reason"),
        requested_at=_state_text(raw, "requested_at"),
        expires_at=_state_optional_text(raw, "expires_at"),
        decision=_state_text(raw, "decision"),
        approver_id=_state_optional_text(raw, "approver_id"),
        decision_reason=_state_optional_text(raw, "decision_reason"),
        decided_at=_state_optional_text(raw, "decided_at"),
    )


def _state_text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"persisted state requires a non-empty {key}")
    return value


def _state_optional_text(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"persisted state requires {key} to be a non-empty string or null")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
