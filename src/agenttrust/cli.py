"""Command line interface for AgentTrust Runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agenttrust.runtime.fixtures import list_fixtures, run_fixture
from agenttrust.runtime.report import resolve_run_dir, timeline_lines, write_markdown_report


DEFAULT_POLICY = """project_root: .
mode: default

rules: []
"""


def _project_root(path: str | None) -> Path:
    return Path(path).resolve() if path else Path.cwd().resolve()


def init_project(project_root: Path) -> Path:
    agenttrust_dir = project_root / ".agenttrust"
    runs_dir = agenttrust_dir / "runs"
    policy_path = agenttrust_dir / "policy.yaml"
    runs_dir.mkdir(parents=True, exist_ok=True)
    if not policy_path.exists():
        policy_path.write_text(DEFAULT_POLICY, encoding="utf-8")
    return agenttrust_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenttrust")
    parser.add_argument("--project-root", help="Project root. Defaults to the current directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize .agenttrust project metadata.")

    fixtures_parser = subparsers.add_parser("fixtures", help="List built-in fixtures.")
    fixtures_parser.set_defaults(command="fixtures")

    run_fixture_parser = subparsers.add_parser("run-fixture", help="Run a deterministic fixture.")
    run_fixture_parser.add_argument("name", help="Fixture name.")
    run_fixture_parser.add_argument("--non-interactive", action="store_true", help="Run in noninteractive mode.")

    replay_parser = subparsers.add_parser("replay", help="Print a run timeline.")
    replay_parser.add_argument("run_id")

    report_parser = subparsers.add_parser("report", help="Generate a minimal markdown report.")
    report_parser.add_argument("run_id")
    report_parser.add_argument("--format", choices=["markdown", "html"], default="markdown")

    policy_parser = subparsers.add_parser("policy", help="Policy helpers.")
    policy_subparsers = policy_parser.add_subparsers(dest="policy_command", required=True)
    validate_parser = policy_subparsers.add_parser("validate", help="Validate that a policy file exists.")
    validate_parser.add_argument("path")

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

    if args.command == "run-fixture":
        init_project(project_root)
        runtime_mode = "noninteractive" if args.non_interactive else "interactive"
        try:
            result = run_fixture(args.name, project_root=project_root, runtime_mode=runtime_mode)
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
            print("HTML reports are planned for a later MVP step.", file=sys.stderr)
            return 2
        report_path = write_markdown_report(resolve_run_dir(project_root, args.run_id))
        print(report_path)
        return 0

    if args.command == "policy" and args.policy_command == "validate":
        policy_path = (project_root / args.path).resolve()
        if not policy_path.exists():
            print(f"policy file not found: {policy_path}", file=sys.stderr)
            return 2
        print(f"valid policy file: {policy_path}")
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
