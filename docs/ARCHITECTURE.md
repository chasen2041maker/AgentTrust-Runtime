# AgentTrust Runtime Architecture

AgentTrust Runtime implements one local-first control path for governed agent tool execution:

```text
Input Source
  -> ToolIntent
  -> Skill/Hook Constraints
  -> Permission Engine
  -> Path Sandbox
  -> Tool Gateway
  -> Append-only Trace
  -> Fact Mapper
  -> GroundGuard FactGate
  -> Replay / Report / Restore
```

## Input Sources

Supported input sources:

- `fixture`: deterministic demos and tests.
- `live_adapter`: the minimal `run-live fake_tool_request` adapter.
- `mcp_lite`: MCP wrapper fixture normalized as `ToolIntent(tool_name="mcp_tool")`.
- `skill_lite`: local `SKILL.md` plus `policy.yaml` bound to a run.

All sources share the same permission, sandbox, gateway, trace, fact mapping, and report path.

## Runtime Controls

- Permission Engine evaluates YAML policy rules with `allow`, `ask`, and `deny`.
- Noninteractive `ask` becomes `deny` with `reason=approval_required`.
- Interactive `ask` records an approval request and waits for approve/deny.
- Test mode uses a mock approver and turns `ask` into `allow`.
- Path Sandbox resolves paths, keeps file operations inside `project_root`, blocks secret files, and records sandbox decisions.
- Hook Lite runs after the tentative permission decision and before sandboxing; hooks can only deny or add trace context.
- Skill Lite loads local tool scope and denies tools outside the selected skill policy.

## Tool Surface

Built-in tools:

- `read_file`
- `write_file`
- `shell`
- `git_diff`

Lite wrapper tools:

- `mcp_tool`
- `skill_context`

The Tool Registry exposes names, categories, input schema, default permission effect, enabled state, and source.

## Run Artifacts

Each run writes artifacts under `.agenttrust/runs/{run_id}/`:

- `trace.jsonl`
- `decisions.json`
- `facts.jsonl`
- `final-answer.md`
- `groundguard-report.json`
- `report.md`
- `report.html`
- `backups/`
- `context-pack.md`
- `context-manifest.json`

Trace is append-only. This implementation does not provide a tamper-evident hash chain.

## Lite Modules

- MCP Lite parses local MCP config, redacts env values, summarizes tool schemas, and routes wrapper calls through the runtime.
- Skill Lite loads local skills and records allowed tools, blocked tools, required facts, and output contracts in trace.
- Recovery Lite backs up `write_file` targets before mutation and records restore previews/applied actions.
- Memory Lite stores explicit project memory, decisions, and run summaries under `.agenttrust/memory/`.
- Context Lite builds deterministic context packs from memory, skill, policy, tool registry, and recent run summaries.
