# Core Concepts

AgentTrust Runtime is built around a small set of auditable objects. Keeping these objects explicit is what makes the runtime deterministic and testable.

## ToolIntent

`ToolIntent` is the normalized request to execute a tool.

It includes:

- `run_id`
- `tool_call_id`
- `tool_name`
- `arguments`
- `source`
- `runtime_mode`

Fixtures, live adapters, MCP wrapper calls, and Skill Lite runs all enter the runtime as `ToolIntent`.

## PermissionDecision

`PermissionDecision` records the policy result before execution:

- `allow`: continue to sandbox/execution.
- `ask`: require approval.
- `deny`: stop before sandbox/execution.

Runtime modes finalize `ask` differently:

| Mode | `ask` Behavior |
| --- | --- |
| `interactive` | Prompt for approve/deny. |
| `noninteractive` | Convert to `deny`, reason `approval_required`. |
| `test` | Convert to `allow`, reason `mock_approver_approved`. |

Tool Registry default effects act as a safety fallback when no policy rule matches.

## SkillDecision

Skill Lite loads local `SKILL.md` and `policy.yaml`.

The policy can define:

- `allowed_tools`
- `blocked_tools`
- `required_fact_keys`
- `output_contract`

If a selected skill blocks a tool, the runtime stops before permission and execution.

## HookDecision

Hook Lite provides a minimal `pre_tool` extension point. Hooks can deny a tool call, but they cannot execute shell commands, call the network, or loosen policy.

## PathSandbox

The sandbox constrains local file operations:

- file reads/writes must stay inside `project_root`;
- secret paths such as `.env`, `*.pem`, and `.ssh/**` are blocked;
- common system directories are blocked;
- write operations resolve the parent directory before mutation.

## ToolResult

`ToolResult` is the normalized result of a tool execution. It can include:

- `status`
- `output_preview`
- `output_digest`
- `metadata`
- `error`

Fact mapping and reporting use `ToolResult`, not raw arbitrary model text.

## Fact

Facts are explicit evidence extracted from tool results. AgentTrust maps:

- `AGENTTRUST_FACTS` blocks in tool output;
- selected metadata from `read_file`, `git_diff`, and `shell`;
- wrapper facts from MCP and Skill Lite fixtures.

GroundGuard receives these facts and checks whether the final answer cites them.

## Run Artifact

Run artifacts are the audit surface:

```text
.agenttrust/runs/{run_id}/
  trace.jsonl
  decisions.json
  facts.jsonl
  final-answer.md
  groundguard-report.json
  report.md
  report.html
  backups/
  context-pack.md
  context-manifest.json
```

The run directory is the unit of replay, reporting, and restore.
