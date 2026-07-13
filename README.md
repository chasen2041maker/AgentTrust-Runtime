<p align="center">
  <img src="docs/assets/agenttrust-mark.svg" width="104" alt="AgentTrust Runtime mark" />
</p>

<h1 align="center">AgentTrust Runtime</h1>

<p align="center">
  <strong>Policy, approvals, recovery, and verifiable evidence for AI agent tool calls.</strong>
</p>

<p align="center">
  Wrap OpenAI Agents, LangGraph, Pydantic AI, MCP, or custom Python tools with fail-closed local controls without replacing the agent framework.
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="docs/index.md">Documentation</a> | <a href="CHANGELOG.md">Changelog</a> | <a href="SECURITY.md">Security</a> | <a href="docs/refactor-roadmap.md">Roadmap</a>
</p>

<p align="center">
  <a href="https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml"><img src="https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB" alt="Python 3.11 or newer" />
  <img src="https://img.shields.io/badge/status-beta-F59E0B" alt="Beta status" />
  <img src="https://img.shields.io/badge/license-MIT-0F766E" alt="MIT License" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Policy-fail--closed-C2410C" alt="Fail-closed policy" />
  <img src="https://img.shields.io/badge/Approvals-resumable-0369A1" alt="Resumable approvals" />
  <img src="https://img.shields.io/badge/Evidence-hash--linked-7C3AED" alt="Hash-linked evidence" />
  <img src="https://img.shields.io/badge/Recovery-governed%20writes-0F766E" alt="Governed write recovery" />
  <img src="https://img.shields.io/badge/MCP-stdio%20%2B%20drift-D97706" alt="MCP stdio and drift controls" />
</p>

![AgentTrust Runtime control flow](docs/assets/runtime-flow.svg)

> **v0.5.1 Beta / developer preview.** AgentTrust is suitable for local development, integration validation, and deterministic control regression. It is not a production-security guarantee. Review permissions, perform threat modeling, and use environment-level safeguards before connecting real systems.

## What is AgentTrust?

An agent framework decides what it wants to do. AgentTrust governs what happens when that decision reaches a real tool.

For each tool call, it answers and records:

1. Is the call allowed, denied, or waiting for human approval?
2. Do its paths, command arguments, MCP trust state, and recovery boundaries pass control checks?
3. Which actor, session, policy snapshot, and arguments produced the result?
4. Can a paused, approved call be replayed with the original arguments after a restart?
5. Does the final answer cite facts recorded in the same session?

It is intentionally a control layer, not an agent planner, model provider, workflow engine, dashboard, or cloud policy service.

## 30-second proof

The package is not published to PyPI yet. Install the current beta directly from this repository, then run a deterministic session that creates evidence, facts, a GroundGuard report, and an HTML report.

```powershell
python -m pip install "agenttrust-runtime @ git+https://github.com/chasen2041maker/AgentTrust-Runtime.git"
mkdir agenttrust-demo
cd agenttrust-demo
agenttrust init
agenttrust run-fixture verified_answer --mode test
agenttrust evidence verify <run_id>
agenttrust report <run_id> --format html
```

Expected evidence verification:

```text
{
  "valid": true,
  "event_count": 11,
  "head_hash": "sha256:..."
}
```

The run directory contains the artifacts that actually occurred on that path:

```text
trace.jsonl             # Local, append-oriented, hash-linked event source
policy-snapshot.yaml    # Exact policy text used for the run
facts.jsonl             # Structured facts mapped from tool results, when present
groundguard-report.json # Final-answer verification result, when finalized
report.md / report.html # Generated from the verified run timeline
```

`trace.jsonl` detects modifications inside its hash chain. It is not externally signed, immutable storage, or a non-repudiation system.

## First governed session

Use an `AgentTrustSession` inside an existing agent loop. This example pauses a code write for approval instead of executing it immediately.

```python
from pathlib import Path

from agenttrust import AgentTrustRuntime

runtime = AgentTrustRuntime(Path("."), runtime_mode="interactive")

with runtime.session(actor_id="alice", agent_id="coding-agent") as session:
    outcome = session.execute(
        "write_file",
        {"path": "src/report.py", "content": "print('hello')\n"},
    )

    if outcome.approval_request:
        print("Approval required:", outcome.approval_request.approval_id)
        print("Evidence:", session.run_dir / "trace.jsonl")
```

Approve and resume the same call with its argument digest still bound to the approval record:

```powershell
agenttrust approvals list
agenttrust approvals inspect <approval_id>
agenttrust approvals approve <approval_id> --reason "reviewed"
agenttrust run resume <run_id>
```

For development installation and test commands, see [Contributing](CONTRIBUTING.md).

## Why AgentTrust?

| Capability | Prompt guardrail | Observability | Sandbox | AgentTrust |
| --- | --- | --- | --- | --- |
| Policy before tool execution | Limited | No | Sometimes | Yes |
| Human approval | Limited | No | No | Resumable |
| Path and tool controls | No | No | Yes | Yes |
| Evidence | No | Trace only | No | Hash-linked local JSONL |
| Restore governed writes | No | No | Snapshot-dependent | Verified run artifacts |
| Final-answer fact check | No | No | No | GroundGuard-backed |
| Replaces an agent framework | No | No | No | No |

The comparison describes scope, not a claim that any single category covers every deployment risk.

## Product highlights

| Policy gate | Resumable approvals | Path and tool controls |
| --- | --- | --- |
| Every tool call evaluates to `allow`, `ask`, or `deny`; unknown tools fail closed. [Concepts](docs/concepts.md) | Pause a session, decide later, and resume the original arguments after verified replay. [CLI](docs/cli.md) | Govern local files, safe shell argv, MCP calls, and custom Python functions. [Architecture](docs/ARCHITECTURE.md) |

| Evidence and replay | Recoverable writes | Final-answer verification |
| --- | --- | --- |
| Store a local hash-linked trace, rebuild SQLite projections, and export spans. [Evidence](docs/concepts.md) | Back up governed file writes and restore through a verified trace. [Recovery](docs/cli.md) | Check required answer claims against facts from the same session. [GroundGuard](docs/concepts.md) |

## How it works

1. Normalize a framework callback, MCP request, or custom callable into a `ToolIntent`.
2. Evaluate policy and registered-tool defaults. Unregistered tools fail closed.
3. Validate file paths, safe shell `argv`, or MCP consent, trust, and command/schema fingerprints.
4. Persist an approval request if the decision is `ask`; otherwise run the governed tool.
5. Append lifecycle events, map facts, and project query state into SQLite.
6. Replay verified evidence for recovery, reporting, OpenTelemetry export, and final-answer verification.

The evidence path is shown separately because SQLite is a rebuildable projection, not the source of truth for a resumed run.

## Integrations

AgentTrust keeps the caller's session rather than making a new run for every wrapped tool.

| Integration | Entry point | Runnable example |
| --- | --- | --- |
| OpenAI Agents SDK | `agenttrust.integrations.openai_agents` | `python examples/openai_agents_sdk_adapter.py` |
| LangGraph | `agenttrust.integrations.langgraph` | `python examples/langgraph_tool_adapter.py` |
| Pydantic AI | `agenttrust.integrations.pydantic_ai` | `python examples/pydantic_ai_adapter.py` |
| Custom Python | `govern()` / `@governed_tool(...)` | [Session API](#first-governed-session) |

The examples use fake-model paths and require no API key. Install framework extras only when using their native objects: `.[openai]`, `.[langgraph]`, or `.[pydantic-ai]`.

## Local MCP stdio governance

AgentTrust separates reading an MCP configuration from starting a server:

```text
static discovery -> inspect -> explicit consent -> tools/list -> tool trust
-> command and schema fingerprint -> tools/call -> evidence
```

```powershell
agenttrust mcp discover
agenttrust mcp inspect <server-or-config>
agenttrust mcp consent grant <server>
agenttrust mcp trust <server> --tool read_file
```

- Discovery and inspection do not start the server or print environment-variable values.
- Real calls require both server consent and tool-level trust.
- Command, description, and input-schema drift invalidate trust and block subsequent calls.
- A missing config fails outside test mode unless the request is explicitly simulated.
- Sandbox profiles are policy metadata today; they are **not** OS-level process or network isolation.

## Evidence, recovery, and reports

![Example evidence report](docs/assets/evidence-report-preview.svg)

Evidence events are append-oriented JSONL records with previous-event hashes. `agenttrust evidence verify` validates a trace before replay, restore, or OpenTelemetry export. `agenttrust state rebuild` can reconstruct the local SQLite projection from verified traces.

For a governed `write_file`, the runtime keeps a run-local backup and validates recovery paths and backup digests. Restoration is file-oriented, should be reviewed, and is not a transaction system for arbitrary side effects.

```powershell
agenttrust evidence verify <run_id>
agenttrust evidence export <run_id>
agenttrust state rebuild
agenttrust restore <run_id> --dry-run
agenttrust report <run_id> --format html
```

Install `.[otel]` to rebuild evidence as OTLP HTTP spans for a backend such as Phoenix, Jaeger, Tempo, or Langfuse. AgentTrust does not ship a dashboard.

## Final-answer verification

`finalize_answer()` records a final answer and checks requested fact keys against facts produced in the current session. This adds a checkable link between a tool result and a claim; it does not prove the completeness or truth of arbitrary model output.

```python
result = session.finalize_answer(
    "Revenue was $3.83 billion [fact:revenue].",
    required_fact_keys=["revenue"],
)
assert result.status == "verified"
```

## Security regression suite

`security-v1` is a public deterministic control regression suite, not a penetration test or a claim of complete coverage against arbitrary agent attacks. It does not execute supplied shell commands or user-configured MCP servers; its first drift case starts only the packaged fake stdio server.

```powershell
agenttrust benchmark security --output benchmark-report.json
```

An execution on the v0.5.1 codebase produced:

```text
107 deterministic checks
100 expected blocks / 100 detected blocks
7 expected-allow baselines
0 false positives / 0 false negatives / 0 critical bypasses
```

The JSON result includes case IDs, expected and observed outcomes, category counts, and policy latency. Reproduce it with the command above; performance depends on your Python and operating-system environment. The public case definitions and limitations are in [the benchmark guide](benchmarks/README.md).

## Use cases

**Coding agents**: require review before source writes or shell execution, then retain recovery artifacts.

**Local MCP clients**: apply explicit consent, per-tool trust, and schema-drift checks to local servers.

**Research and data agents**: retain tool-produced facts and check final reports against them.

**Regulated or audited workflows**: keep actor, session, policy, approval, tool-result, and final-answer evidence together.

## Project status and limitations

**Status: Beta.** The runtime has production-shaped local controls, but it is still a developer preview.

Available now:

- Session-scoped execution, persisted approval records, and replay from verified local evidence.
- Local MCP stdio consent, tool trust, and drift checks.
- Hash-linked evidence, SQLite projection rebuild, report generation, and OTLP export.
- GroundGuard-backed checks for required facts in a final answer.

Known limitations:

- Local evidence has no external signature, trusted timestamp, or immutable storage anchor.
- Runtime session serialization is in-process; do not resume the same run from multiple processes.
- Custom functions wrapped with `govern()` must be registered again after a restart before resume.
- Approval expiry is enforced when an expiry exists, but a configurable default approval TTL is not yet available.
- MCP sandbox profiles do not enforce OS-level process or network isolation.
- File restoration is not a general-purpose transaction or rollback mechanism.

## Roadmap

The next reliability work focuses on cross-process run coordination, configurable approval lifetimes, stronger evidence anchoring, successful-write recovery binding, and OS-level MCP isolation. The broader implementation history and planned boundaries are in the [architecture roadmap](docs/refactor-roadmap.md) and [enterprise architecture](docs/enterprise-architecture.md).

## Documentation

- [Getting started](docs/getting-started.md)
- [CLI reference](docs/cli.md)
- [Core concepts](docs/concepts.md)
- [Runtime architecture](docs/ARCHITECTURE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Related work and boundaries](docs/RELATED_WORK.md)
- [Benchmark guide](benchmarks/README.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)

## Community and contributing

Contributions are welcome when they strengthen a concrete, deterministic runtime control. Start with [CONTRIBUTING.md](CONTRIBUTING.md), open an issue with a focused reproduction, and report potential security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
