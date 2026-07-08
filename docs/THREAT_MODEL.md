# Threat Model

## Scope

AgentTrust Runtime protects local developer workflows where an agent can request file, shell, git, and write operations through Tool Gateway.

## Assets

- Project source code
- Secret files such as `.env`, PEM files, and SSH keys
- Run trace and fact ledger
- Final answer report

## Trust Boundaries

- Agent output is untrusted
- Tool arguments are untrusted until checked
- File system outside `project_root` is untrusted and out of scope
- Tool output is evidence only after mapper records structured facts
- GroundGuard-style verification checks recorded facts, not arbitrary truth

## Attacker Capabilities

- Prompt injection causes agent to request dangerous tools
- Agent attempts to read secret files
- Agent attempts to write project files without approval
- Agent attempts dangerous shell commands
- Agent outputs unsupported or contradicted final claims

## Covered Controls

- Permission Engine `allow` / `ask` / `deny`
- Path Sandbox
- Dangerous shell deny rules
- Noninteractive `ask -> deny`
- Append-only trace
- Structured fact verification

## Explicit Non-Goals

- No network egress control in MVP
- No MCP scanner or MCP Lite in MVP
- No MCP proxy in MVP
- No Skill Lite, skill marketplace, or remote skill installation in MVP
- No multi-agent coordination controls
- No Memory Lite or automatic long-term persona memory in MVP
- No Context Lite or LLM-based context compaction in MVP
- No TUI in MVP
- No full git worktree manager in MVP
- No subagent/team orchestration in MVP
- No tamper-evident hash chain in MVP
- No complete OWASP Agentic Top 10 coverage
- No universal natural language fact checking

## Abuse Cases

1. Read `.env`
2. Read `~/.ssh/id_rsa`
3. Symlink escape outside `project_root`
4. Execute `rm -rf /`
5. Write source file in noninteractive mode
6. Produce final answer with contradicted revenue number
7. Produce final answer with unverified revenue number

## Residual Risk

The runtime can block configured local actions and verify structured facts, but it cannot prove model intent, cannot detect every malicious output, and cannot secure tools that bypass Tool Gateway.
