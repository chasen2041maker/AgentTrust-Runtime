# Changelog

All notable changes to AgentTrust Runtime are documented here.

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
