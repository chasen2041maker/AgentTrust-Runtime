# AgentTrust Runtime Architecture

AgentTrust Runtime implements one narrow local-first control path for agent tool execution:

```text
Input Source
  -> ToolIntent
  -> Tool Gateway
  -> Permission Engine
  -> Path Sandbox
  -> Tool Execution
  -> Append-only Trace
  -> Fact Mapper
  -> GroundGuard-style FactGate
  -> Replay / Report
```

## Input Sources

MVP input sources:

- `fixture`: deterministic demos and tests.
- `live_adapter`: the minimal `run-live fake_tool_request` adapter.

Both sources create `ToolIntent` objects and then share the same Gateway, permission, sandbox, trace, fact mapping, and report path.

## Runtime Controls

- Permission Engine evaluates YAML policy rules with `allow`, `ask`, and `deny`.
- Noninteractive `ask` becomes `deny` with `reason=approval_required`.
- Test mode uses a mock approver and turns `ask` into `allow`.
- Path Sandbox resolves paths, keeps file operations inside `project_root`, blocks secret files, and records sandbox decisions.
- Tool Gateway dispatches only built-in MVP tools: `read_file`, `write_file`, `shell`, and `git_diff`.

## Run Artifacts

Each run writes artifacts under `.agenttrust/runs/{run_id}/`:

- `trace.jsonl`
- `decisions.json`
- `facts.jsonl`
- `final-answer.md`
- `groundguard-report.json`
- `report.md`
- `report.html`

Trace is append-only. MVP does not implement a tamper-evident hash chain.
