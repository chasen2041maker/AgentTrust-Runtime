# AgentTrust Runtime Docs

AgentTrust Runtime is a local-first governance layer for AI agent tool execution. It turns tool requests into auditable `ToolIntent` objects, applies permission and sandbox controls, records run artifacts, and routes final-answer facts into GroundGuard.

## Start Here

- [Getting started](getting-started.md): install, initialize, and run the first fixtures.
- [CLI reference](cli.md): commands grouped by workflow.
- [Core concepts](concepts.md): the objects and decisions that make up the runtime.
- [Architecture](ARCHITECTURE.md): module boundaries and control flow.
- [Threat model](THREAT_MODEL.md): covered controls, non-goals, and residual risk.
- [Related work and scope](RELATED_WORK.md): where AgentTrust fits next to governance, tracing, and fact-gate tools.
- [Changelog](../CHANGELOG.md): notable changes.
- [Contributing](../CONTRIBUTING.md): development setup and contribution rules.
- [Security](../SECURITY.md): security scope and artifact hygiene.

## What The Runtime Proves

AgentTrust is intentionally small. It proves that a local runtime can:

1. Normalize agent tool requests before execution.
2. Gate risky actions with policy, hooks, skills, and sandbox checks.
3. Keep replayable trace and decision artifacts.
4. Backup local writes and restore them by run id.
5. Map tool results into structured facts.
6. Ask GroundGuard whether the final answer is supported by those facts.

## Main Demo Paths

```bash
agenttrust run-fixture blocked_secret
agenttrust run-fixture mcp_tool_approved --mode test
agenttrust run-fixture skill_code_review
agenttrust run-fixture write_and_restore --mode test
agenttrust run-fixture memory_context_pack
```

After any run:

```bash
agenttrust replay <run_id>
agenttrust report <run_id> --format html
```
