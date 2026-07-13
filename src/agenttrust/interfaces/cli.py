"""Command line interface for AgentTrust Runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agenttrust.context_lite import build_context_pack, export_context_to_run
from agenttrust.benchmark.security import run_security_benchmark
from agenttrust.adapters.mcp.runtime import list_server_tools
from agenttrust.mcp_lite import (
    discover_mcp_servers,
    grant_mcp_consent,
    has_mcp_consent,
    inspect_mcp_config,
    resolve_mcp_server,
    revoke_mcp_consent,
    trust_mcp_server,
    trust_mcp_server_surface,
)
from agenttrust.memory_lite import add_memory, clear_memory, list_memory
from agenttrust.adapters.policy.yaml_policy import DEFAULT_POLICY_TEXT, load_policy
from agenttrust.runtime.fixtures import list_fixtures, run_fixture
from agenttrust.runtime.live import run_live
from agenttrust.runtime.recovery import restore_run
from agenttrust.runtime.report import resolve_run_dir, timeline_lines, write_html_report, write_markdown_report
from agenttrust.runtime.trace import verify_trace
from agenttrust.adapters.evidence.export import export_ndjson
from agenttrust.adapters.evidence.otel import export_otel_trace
from agenttrust.adapters.evidence.run_lock import RunLock
from agenttrust.interfaces.python_api import AgentTrustRuntime
from agenttrust.adapters.evidence.approval_journal import JsonlApprovalJournal
from agenttrust.adapters.evidence.jsonl_store import TraceRecorder, read_trace
from agenttrust.adapters.evidence.projecting_recorder import ProjectingTraceRecorder
from agenttrust.adapters.evidence.replay import replay_verified_run
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
    restore_parser.add_argument("--apply", action="store_true", help="Apply the restore instead of previewing it.")
    restore_parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    restore_parser.add_argument("--force", action="store_true", help="Apply despite a post-write digest conflict.")

    evidence_parser = subparsers.add_parser("evidence", help="Evidence integrity helpers.")
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_command", required=True)
    evidence_verify = evidence_subparsers.add_parser("verify", help="Verify a run evidence hash chain.")
    evidence_verify.add_argument("run_id")
    evidence_export = evidence_subparsers.add_parser("export", help="Export run evidence as NDJSON.")
    evidence_export.add_argument("run_id")
    evidence_otel = evidence_subparsers.add_parser("export-otel", help="Export run evidence to an OTLP HTTP endpoint.")
    evidence_otel.add_argument("run_id")
    evidence_otel.add_argument("--endpoint", required=True)

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

    mcp_parser = subparsers.add_parser("mcp", help="MCP gateway helpers.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_subparsers.add_parser("discover", help="Statically discover local MCP configs without starting servers.")
    mcp_inspect = mcp_subparsers.add_parser("inspect", help="Inspect an MCP config.")
    mcp_inspect.add_argument("target", help="A config path or discovered server name.")
    mcp_consent = mcp_subparsers.add_parser("consent", help="Grant consent for a local MCP server.")
    mcp_consent.add_argument("action_or_server", help="grant/revoke plus server, or a legacy server name to grant")
    mcp_consent.add_argument("server", nargs="?")
    mcp_trust = mcp_subparsers.add_parser("trust", help="Trust an MCP server tool.")
    mcp_trust.add_argument("server")
    mcp_trust.add_argument("--tool", action="append", required=True)
    mcp_trust.add_argument("--sandbox-profile", choices=["strict", "standard"], default="strict")

    benchmark_parser = subparsers.add_parser("benchmark", help="Run deterministic local security benchmarks.")
    benchmark_subparsers = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)
    security_benchmark = benchmark_subparsers.add_parser("security", help="Run the versioned 100-case security benchmark.")
    security_benchmark.add_argument("--output", help="Write the JSON report to this path.")

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
        try:
            run_dir = resolve_run_dir(project_root, args.run_id)
            for line in timeline_lines(run_dir):
                print(line)
        except (OSError, ValueError) as exc:
            print(f"replay failed: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "report":
        try:
            if args.format == "html":
                report_path = write_html_report(resolve_run_dir(project_root, args.run_id))
            else:
                report_path = write_markdown_report(resolve_run_dir(project_root, args.run_id))
        except (OSError, ValueError) as exc:
            print(f"report failed: {exc}", file=sys.stderr)
            return 2
        print(report_path)
        return 0

    if args.command == "restore":
        try:
            actions = restore_run(
                resolve_run_dir(project_root, args.run_id),
                only_file=args.file,
                dry_run=not args.apply or args.dry_run,
                force=args.force,
            )
        except (OSError, ValueError) as exc:
            print(f"restore failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(actions, ensure_ascii=False, indent=2))
        return 0

    if args.command == "evidence" and args.evidence_command == "verify":
        verification_result = verify_trace(resolve_run_dir(project_root, args.run_id) / "trace.jsonl")
        print(json.dumps(verification_result, ensure_ascii=False, indent=2))
        return 0 if verification_result["valid"] else 2

    if args.command == "evidence" and args.evidence_command == "export":
        try:
            print(export_ndjson(resolve_run_dir(project_root, args.run_id)))
        except (OSError, ValueError) as exc:
            print(f"evidence export failed: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "evidence" and args.evidence_command == "export-otel":
        try:
            count = export_otel_trace(resolve_run_dir(project_root, args.run_id), endpoint=args.endpoint)
        except (RuntimeError, ValueError) as exc:
            print(f"OpenTelemetry export failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"spans_exported": count}, ensure_ascii=False))
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
            approval = _approval_from_verified_evidence(project_root, args.approval_id)
            if approval is None:
                print(f"approval not found: {args.approval_id}", file=sys.stderr)
                return 2
            print(json.dumps(approval.to_dict(), ensure_ascii=False, indent=2))
            return 0
        approval = _approval_from_verified_evidence(project_root, args.approval_id)
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

    if args.command == "mcp" and args.mcp_command == "discover":
        print(json.dumps({"servers": discover_mcp_servers(project_root)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "mcp" and args.mcp_command == "inspect":
        try:
            candidate_path = (project_root / args.target).resolve()
            if candidate_path.exists():
                payload = inspect_mcp_config(candidate_path)
            else:
                config = resolve_mcp_server(project_root, args.target)
                if config is None:
                    raise ValueError(f"MCP server not found: {args.target}")
                payload = inspect_mcp_config(config.config_path)
                payload["servers"] = [server for server in payload["servers"] if server.get("name") == config.name]
        except (OSError, ValueError) as exc:
            print(f"invalid MCP config: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "mcp" and args.mcp_command == "consent":
        if args.action_or_server in {"grant", "revoke"}:
            if not args.server:
                print(f"mcp consent {args.action_or_server} requires a server name", file=sys.stderr)
                return 2
            action = args.action_or_server
            server_name = args.server
        else:
            action = "grant"
            server_name = args.action_or_server
        if action == "grant":
            print(grant_mcp_consent(project_root, server_name))
        else:
            print(revoke_mcp_consent(project_root, server_name))
        return 0

    if args.command == "mcp" and args.mcp_command == "trust":
        try:
            config = resolve_mcp_server(project_root, args.server)
            if config is None:
                print(trust_mcp_server(project_root, args.server, args.tool, args.sandbox_profile))
                return 0
            if not has_mcp_consent(project_root, args.server):
                raise ValueError(f"MCP server '{args.server}' requires explicit consent before trust")
            path = trust_mcp_server_surface(
                project_root,
                config,
                list_server_tools(config),
                args.tool,
                args.sandbox_profile,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"MCP trust failed: {exc}", file=sys.stderr)
            return 2
        print(path)
        return 0

    if args.command == "benchmark" and args.benchmark_command == "security":
        report = run_security_benchmark(project_root / ".agenttrust" / "benchmarks" / "security-v1")
        if args.output:
            output_path = report.write_json((project_root / args.output).resolve())
            print(output_path)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.false_negatives == 0 and report.critical_bypasses == 0 else 2

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
    approval: ApprovalRequest,
    *,
    decision: str,
    approver_id: str,
    reason: str,
) -> ApprovalRequest:
    if not approval.is_pending:
        raise ValueError(f"approval {approval.approval_id} has already been decided")
    run_dir = resolve_run_dir(project_root, approval.run_id)
    with RunLock(run_dir) as operation_lock:
        return _decide_approval_locked(
            state,
            approval,
            decision=decision,
            approver_id=approver_id,
            reason=reason,
            run_dir=run_dir,
            operation_lock=operation_lock,
        )


def _decide_approval_locked(
    state: SQLiteStateProjection,
    approval: ApprovalRequest,
    *,
    decision: str,
    approver_id: str,
    reason: str,
    run_dir: Path,
    operation_lock: RunLock,
) -> ApprovalRequest:
    replayed = replay_verified_run(run_dir)
    replayed_approval = next(
        (item for item in replayed.approvals if item.approval_id == approval.approval_id),
        None,
    )
    if replayed_approval is None or replayed_approval != approval:
        raise ValueError("approval source trace no longer matches the requested approval")
    recorder = TraceRecorder(run_dir, run_lock=operation_lock)
    recorder.bind(
        actor_id=replayed.session.actor_id,
        agent_id=replayed.session.agent_id,
        session_id=replayed.session.session_id,
        policy_version=replayed.session.policy_version,
    )
    expired = approval.is_expired()
    if expired:
        decided = approval.expire(approver_id)
    elif decision == "approve":
        decided = approval.approve(approver_id, reason)
    elif decision == "deny":
        decided = approval.deny(approver_id, reason)
    else:
        raise ValueError(f"unknown approval decision: {decision}")
    state.rebuild()
    evidence = ProjectingTraceRecorder(recorder, state)
    if expired:
        evidence.append(
            "approval_expired",
            run_id=approval.run_id,
            tool_call_id=approval.tool_call_id,
            approval_id=approval.approval_id,
            expires_at=approval.expires_at,
        )
    event = evidence.append("approval_decided", **decided.to_dict())
    JsonlApprovalJournal(run_dir).append(event)
    return decided


def _approval_from_verified_evidence(project_root: Path, approval_id: str) -> ApprovalRequest | None:
    """Use raw trace text only to locate an approval, then verify and replay that run."""

    candidates: list[Path] = []
    for trace_path in sorted((project_root / ".agenttrust" / "runs").glob("*/trace.jsonl")):
        if any(event.get("approval_id") == approval_id for event in read_trace(trace_path)):
            candidates.append(trace_path.parent)
    if len(candidates) > 1:
        raise ValueError(f"approval id appears in multiple evidence traces: {approval_id}")
    if not candidates:
        return None
    replayed = replay_verified_run(candidates[0])
    return next((item for item in replayed.approvals if item.approval_id == approval_id), None)


if __name__ == "__main__":
    raise SystemExit(main())
