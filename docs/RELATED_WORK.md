# Related Work and Scope

AgentTrust Runtime is a small local-first implementation for learning and portfolio review. It is not a replacement for Microsoft Agent Governance Toolkit, Invariant MCP-Scan, Cisco MCP Scanner, Snyk Agent Scan, AgentOps, Braintrust, or Phoenix.

Those projects cover production governance, MCP/skills scanning, observability, or enterprise workflows at broader scope. This project focuses on one inspectable path: policy-gated local tool execution, replayable traces, recovery for local writes, controlled context assembly, and GroundGuard-backed structured fact verification in the same run artifact.

## Implemented Scope

The repository now includes:

- Permission checks before local tool execution
- Path sandbox checks
- Append-only trace
- Deterministic fixtures
- Structured fact mapping
- Replayable markdown and HTML reports
- MCP Lite config inspection and wrapper calls
- Skill Lite local loader and tool-scope enforcement
- Recovery Lite for `write_file`
- Tool Registry Lite
- Hook Lite `pre_tool` denial rules
- Memory Lite and Context Lite

## Deliberate Boundary

AgentTrust Runtime still does not attempt to be a full production platform. It does not implement a remote MCP proxy, skill marketplace, cloud policy service, full observability backend, TUI coding assistant, automatic long-term persona memory, or tamper-evident audit hash chain.
