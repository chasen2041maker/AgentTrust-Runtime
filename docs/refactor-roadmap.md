# Refactor Roadmap

This roadmap turns the current working runtime into the layered architecture described in [Enterprise Architecture Upgrade](enterprise-architecture.md).

## Implementation Status

Completed in the first refactor increment:

- Phase 1 domain extraction: `ToolIntent`, `ToolResult`, policy rules, hook rules, and permission/sandbox decisions now live in `agenttrust.domain`.
- Old `schemas.py` and `permissions.*` paths remain compatibility exports, so current CLI and library consumers keep working.
- Import-boundary tests enforce that the domain has no CLI, YAML, subprocess, filesystem, or concrete-tool dependency.

In progress for Phase 2:

- `agenttrust.application` now defines explicit ports plus `RunToolUseCase`, `RunFixtureUseCase`, `BuildContextUseCase`, and `RestoreRunUseCase`.
- The current fixture and live entrypoints compose `RunToolUseCase` with existing local adapters, preserving their evidence event sequence.
- Application tests use in-memory ports; concrete adapter extraction remains the next migration step.

## Current Architecture Snapshot

The current codebase is compact and testable:

```text
src/agenttrust/
  cli.py
  schemas.py
  permissions/
  runtime/
  tools/
  groundguard_adapter/
  mcp_lite.py
  skills_lite.py
  memory_lite.py
  context_lite.py
```

Strengths:

- deterministic fixtures;
- clear CLI;
- working permission/sandbox/trace/fact/report loop;
- Roadmap Lite features are covered by tests;
- GroundGuard integration exists.

Remaining architectural debt:

- fixture setup still owns skill, memory, context, and final-answer orchestration;
- CLI directly invokes concrete helpers;
- several concrete adapters still live under their original feature modules;
- enterprise metadata such as actor/session/policy version is not yet modeled;
- evidence is append-only but not tamper-evident.

## Target Package Map

| Current Module | Target Layer | Migration Notes |
| --- | --- | --- |
| `schemas.py` | `domain/models.py` | Keep `schemas.py` as re-export during migration. |
| `permissions/policy.py` | `domain/policy.py` + `adapters/policy/yaml_policy.py` | Split pure rules from YAML loading. |
| `permissions/engine.py` | `application/policy_evaluator.py` | Depend on domain policy and tool registry port. |
| `permissions/sandbox.py` | `adapters/sandbox/filesystem.py` | Expose `SandboxPort`. |
| `runtime/fixtures.py` | `interfaces/fixtures.py` + `application/run_fixture.py` | Fixture specs should be input data, not orchestrator logic. |
| `runtime/gateway.py` | `application/tool_gateway.py` + `adapters/tools/*` | Gateway should depend on `ToolExecutorPort`. |
| `runtime/recovery.py` | `application/restore_run.py` + `adapters/evidence/jsonl_store.py` | Restore use case should read backups via evidence port. |
| `runtime/trace.py` | `adapters/evidence/jsonl_store.py` | Later add hash-chain store. |
| `groundguard_adapter/*` | `adapters/verification/groundguard.py` | Expose `FactVerifierPort`. |
| `mcp_lite.py` | `adapters/mcp/config_inspector.py` | Later add consent/trust registry. |
| `skills_lite.py` | `adapters/skills/local_loader.py` | Domain owns `SkillContract`. |
| `memory_lite.py` / `context_lite.py` | `application/context_pack.py` + adapters | Context pack becomes a use case. |

## Phase 1: Domain Extraction

Deliverables:

- `src/agenttrust/domain/models.py`
- `src/agenttrust/domain/decisions.py`
- `src/agenttrust/domain/policy.py`
- compatibility re-exports from old modules
- import-boundary tests

Validation:

```bash
python -m pytest
python -m pytest tests/test_architecture_boundaries.py
```

Done when:

- no CLI behavior changes;
- domain layer imports only standard library and domain modules;
- current public imports still work.

## Phase 2: Application Use Cases

Deliverables:

- `src/agenttrust/application/ports.py`
- `src/agenttrust/application/run_tool.py`
- `src/agenttrust/application/run_fixture.py`
- `src/agenttrust/application/restore_run.py`
- `src/agenttrust/application/build_context.py`

Validation:

- use-case tests run with in-memory adapters;
- fixture tests still produce identical event types;
- CLI uses application use cases instead of concrete helpers.

## Phase 3: Adapter Split

Deliverables:

- `adapters/tools`
- `adapters/policy`
- `adapters/evidence`
- `adapters/sandbox`
- `adapters/verification`
- `interfaces/cli.py`

Validation:

- application layer imports no concrete adapters;
- adapters implement ports;
- current CLI remains stable.

## Phase 4: Enterprise Evidence

Deliverables:

- policy snapshot per run;
- actor/session metadata;
- evidence event hash chain;
- `agenttrust evidence verify <run_id>`;
- SIEM/OTel export adapter design.

Validation:

- tampering with one trace line fails evidence verification;
- reports include actor/session/policy metadata;
- recovery events are included in evidence verification.

## Phase 5: Enterprise MCP And Framework Integration

Deliverables:

- MCP trusted server registry;
- MCP consent record;
- command allowlist and risk display;
- framework adapter examples for OpenAI Agents SDK / LangGraph-style loops;
- Python SDK entrypoint for custom loops.

Validation:

- local MCP command requires explicit consent before first use;
- risky command patterns are surfaced before execution;
- tool calls from framework adapters still produce identical AgentTrust artifacts.

## Recommended Immediate PR

Keep the first refactor small:

1. Add `domain/models.py`.
2. Re-export from `schemas.py`.
3. Add `tests/test_architecture_boundaries.py`.
4. Move no runtime behavior yet.

This creates the architecture seam while keeping the risk low.
