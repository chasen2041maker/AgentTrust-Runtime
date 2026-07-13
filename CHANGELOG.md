# Changelog

All notable changes to AgentTrust Runtime are documented here.

## 0.5.0 - 2026-07-13

### Added

- Session-scoped runtime with durable lifecycle state, shared identity and policy snapshots, sequential tool calls, timeout handling, cancellation, and persisted approvals that bind the approved argument digest.
- `finalize_answer()` lifecycle with GroundGuard-backed fact checks and policy modes for warning, denial, or revision.
- `govern()` and `@governed_tool` for ordinary synchronous Python functions, plus session-reusing integrations for OpenAI Agents SDK, LangGraph, and Pydantic AI.
- Real local MCP stdio transport with static discovery, explicit consent, tool-level trust, command/schema fingerprints, drift invalidation, and structured transport evidence.
- SQLite state projection and `agenttrust state rebuild` recovery from verified JSONL evidence.
- OpenTelemetry evidence export through `agenttrust evidence export-otel <run_id> --endpoint <url>`.
- Public deterministic `security-v1` benchmark with 100 adversarial cases and JSON metrics via `agenttrust benchmark security`.
- Runnable, API-key-free examples for the three supported framework integrations.

### Changed

- `shell` now defaults to `ask` and safe shell execution accepts argv with `shell=False`; compatibility behavior is explicitly named `unsafe_shell_command`.
- Unregistered tools now fail closed at permission evaluation.
- Evidence is hash-linked JSONL backed by a queryable SQLite projection; run state can be reconstructed from verified source evidence.

### Security

- MCP servers require persisted consent before trust or real transport use, and trusted tools are denied after command or schema drift.
- The security benchmark covers path escape, secret access, shell injection, approval bypass, MCP drift, evidence tampering, and fact contradiction controls.

## 0.1.0 - 2026-07-09

### Added

- Enterprise architecture upgrade plan and phased refactor roadmap.
- Framework-free `domain` package for execution models, policy rules, hook rules, and decision records.
- Explicit application ports and use cases for governed tool execution, fixture normalization, context packs, and restore operations.
- Architecture boundary and in-memory application-use-case tests.
- Core local-first runtime path:
  - `ToolIntent` / `ToolResult`
  - Permission Engine
  - Path Sandbox
  - Tool Gateway
  - append-only run trace
  - fact mapper
  - GroundGuard adapter
  - replay and report generation
- Built-in tools:
  - `read_file`
  - `write_file`
  - `shell`
  - `git_diff`
- Lite roadmap modules:
  - MCP Lite
  - Skill Lite
  - Recovery Lite
  - Tool Registry Lite
  - Hook Lite
  - Memory Lite
  - Context Lite
- Deterministic fixtures for permission, sandbox, fact verification, MCP, skill, hook, recovery, and context paths.
- Chinese README and project documentation aligned with the GroundGuard documentation style.

### Security

- Secret path blocking for `.env`, PEM files, and SSH paths.
- Tool Registry default-effect fallback for risky tools such as `mcp_tool`.
- Restore path constraints for project root and run-local backups.

### Changed

- Fixture and live tool execution now run through the application-layer `RunToolUseCase` while preserving existing CLI behavior and evidence event ordering.
- Legacy schema and permission import paths now re-export the domain objects for migration compatibility.
- YAML policy loading, filesystem sandboxing, JSONL trace storage, and the local tool gateway now have explicit adapter-layer homes with compatibility facades.
- Recovery checkpoints and restore operations now live in the JSONL evidence adapter.
- Local file, shell, Git, MCP, skill, and GroundGuard verification implementations now live under `adapters` with compatibility imports preserved.
- Runs now record actor/session metadata, exact policy snapshots, and a verifiable JSONL evidence hash chain.
- Local MCP execution now requires explicit persisted consent outside deterministic test mode.
