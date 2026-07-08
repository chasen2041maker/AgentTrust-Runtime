# AgentTrust Runtime

AgentTrust Runtime is a local-first Python runtime design for governed agent tool execution.

The goal is a small, deterministic, testable implementation of one core control path: turn every agent tool request into an auditable `ToolIntent`, enforce permission and path sandbox rules before execution, record replayable traces, and verify final structured claims with GroundGuard.

## Current Status

This repository currently contains the merged final implementation plan. Runtime implementation is the next step.

See the [final implementation plan](AgentTrust-Runtime-%E6%9C%80%E7%BB%88%E5%AE%9E%E6%96%BD%E6%96%B9%E6%A1%88.md) for the full MVP scope and roadmap.

## Core Runtime Path

```text
Input Source
  -> ToolIntent
  -> Tool Gateway
  -> Permission Engine
  -> Path Sandbox
  -> Tool Execution
  -> Append-only Trace
  -> Fact Mapper
  -> GroundGuard FactGate
  -> Replay / Report
```

Fixtures and the minimal live adapter must use the same Gateway, Permission Engine, Sandbox, Trace Recorder, and FactGate path. Fixtures are only an input source, not a separate demo script.

## MVP Scope

The MVP is intentionally narrow:

- ToolIntent and ToolResult schemas
- Tool Gateway
- Permission Engine with `allow`, `ask`, and `deny`
- Path Sandbox
- Built-in tools: `read_file`, `write_file`, `shell`, `git_diff`
- Append-only `trace.jsonl`
- Deterministic fixtures
- GroundGuard adapter
- Replay and report generation
- Minimal live adapter: `run-live fake_tool_request`
- README, threat model, related work, tests, and CI

The MVP is not a full enterprise governance platform, a full MCP scanner, a coding assistant, a SaaS product, or a replacement for existing agent observability and governance tools.

## Target CLI

These are the planned MVP commands:

```bash
agenttrust init

agenttrust run-fixture blocked_secret
agenttrust run-fixture ask_noninteractive --non-interactive
agenttrust run-fixture verified_answer
agenttrust run-fixture contradicted_answer
agenttrust run-fixture unverified_answer

agenttrust run-live fake_tool_request

agenttrust replay <run_id>
agenttrust report <run_id>
agenttrust report <run_id> --format markdown
agenttrust report <run_id> --format html

agenttrust policy validate .agenttrust/policy.yaml
```

## Demo Fixtures

The MVP demos are designed to be deterministic and testable:

- `blocked_secret`: agent requests `.env`; runtime denies access.
- `ask_noninteractive`: write request becomes `ask`, then `deny` in noninteractive mode.
- `verified_answer`: final answer is supported by recorded facts.
- `contradicted_answer`: final answer contradicts recorded facts.
- `unverified_answer`: final answer omits required evidence.

## Why GroundGuard

AgentTrust Runtime does not try to solve general hallucination detection. It verifies structured fact coverage for facts explicitly recorded from tool outputs, especially numeric claims, tool metadata, and run artifacts.

The MVP will reuse GroundGuard for fact recording, coverage checks, and reporting. AgentTrust only adds the runtime-side adapter that maps tool results and fixture outputs into structured facts.

## Roadmap

The following ideas are deliberately outside the MVP:

- MCP Lite: inspect local MCP config and wrap known MCP tool calls as ToolIntent.
- Skill Lite: bind local `SKILL.md` instructions, tool scope, required facts, and output contracts to a run.
- Recovery Lite: back up files before `write_file` and restore changes by run id.
- Tool Registry Lite: list and inspect tool schemas, scopes, and default effects.
- Hook Lite: add a constrained `pre_tool` extension point that can only tighten decisions.
- Memory Lite and Context Lite: explicit local project memory, run summaries, deterministic context packs, and budget trimming.

These features must remain subordinate to the core runtime path. If a feature does not strengthen permission, sandbox, trace, FactGate, or report, it should stay out of the MVP.

## Related Work and Scope

AgentTrust Runtime is a small local-first implementation for learning and portfolio review. It is not a replacement for Microsoft Agent Governance Toolkit, Invariant MCP-Scan, Cisco MCP Scanner, Snyk Agent Scan, AgentOps, Braintrust, or Phoenix. Those projects cover production governance, MCP/skills scanning, or observability at broader scope.

This project focuses on one narrow path: policy-gated local tool execution, replayable traces, and GroundGuard-backed fact verification in the same run artifact.

## Next Step

Start Week 1 implementation:

- create the Python package skeleton
- implement `agenttrust init`
- implement `agenttrust run-fixture`
- define ToolIntent and ToolResult
- write append-only trace events
- add `read_file` and `git_diff`
- make sure fixtures go through the Gateway
