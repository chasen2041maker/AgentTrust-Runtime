# Related Work and Scope

AgentTrust Runtime is a small local-first implementation for learning and portfolio review. It is not a replacement for Microsoft Agent Governance Toolkit, Invariant MCP-Scan, Cisco MCP Scanner, Snyk Agent Scan, AgentOps, Braintrust, or Phoenix.

Those projects cover production governance, MCP/skills scanning, or observability at broader scope. This project focuses on one narrow path: policy-gated local tool execution, replayable traces, and GroundGuard-backed structured fact verification in the same run artifact.

## Deliberate Scope Boundary

MVP focuses on:

- Permission before local tool execution
- Path sandbox checks
- Append-only trace
- Deterministic fixtures
- Structured fact mapping
- Replayable reports

Roadmap work such as MCP Lite, Skill Lite, Recovery Lite, Tool Registry Lite, Hook Lite, Memory Lite, and Context Lite stays outside the MVP unless it strengthens the core runtime path.
