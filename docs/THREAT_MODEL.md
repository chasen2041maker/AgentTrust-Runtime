# Threat Model

## Scope

AgentTrust Runtime protects local developer workflows where an agent can request file, shell, git, MCP wrapper, skill-context, and write operations through Tool Gateway.

## Assets

- Project source code
- Secret files such as `.env`, PEM files, and SSH keys
- Run trace and fact ledger
- Permission and hook decisions
- Recovery backups
- Memory and context artifacts
- Final answer report

## Trust Boundaries

- Agent output is untrusted
- Tool arguments are untrusted until checked
- MCP configs are inspected locally and env values are not exposed in CLI output
- Skill instructions are local project files, not trusted remote marketplace packages
- File system outside `project_root` is untrusted and out of scope
- Tool output is evidence only after mapper records structured facts
- GroundGuard verification checks recorded facts, not arbitrary truth

## Attacker Capabilities

- Prompt injection causes agent to request dangerous tools
- Agent attempts to read secret files
- Agent attempts to write project files without approval
- Agent attempts dangerous shell commands
- Agent attempts to invoke MCP wrapper tools without approval
- Agent attempts to use a tool blocked by a selected skill
- Agent outputs unsupported or contradicted final claims

## Covered Controls

- Permission Engine `allow` / `ask` / `deny`
- Interactive approve/deny handling
- Noninteractive `ask -> deny`
- Test-mode mock approval
- Path Sandbox
- Dangerous shell deny rules
- MCP wrapper default `ask`
- Skill tool-scope enforcement
- `pre_tool` hooks that can deny before sandbox/execution
- `write_file` backups and restore trace events
- Append-only trace
- Structured fact verification
- Deterministic context pack manifests

## Explicit Non-Goals

- No remote MCP proxy
- No remote skill marketplace or dynamic skill installation
- No network egress control
- No multi-agent coordination controls
- No automatic long-term persona memory
- No LLM-based context compaction
- No TUI
- No full git worktree manager
- No subagent/team orchestration
- No tamper-evident hash chain
- No complete OWASP Agentic Top 10 coverage
- No universal natural language fact checking

## Abuse Cases

1. Read `.env`
2. Read `~/.ssh/id_rsa`
3. Symlink escape outside `project_root`
4. Execute `rm -rf /`
5. Write source file in noninteractive mode
6. Invoke `mcp_tool` in noninteractive mode
7. Use a tool blocked by `code-review` skill policy
8. Produce final answer with contradicted revenue number
9. Produce final answer with unverified revenue number
10. Restore a file modified by `write_file`

## Residual Risk

The runtime can block configured local actions, restore local writes that went through `write_file`, and verify structured facts, but it cannot prove model intent, cannot detect every malicious output, and cannot secure tools that bypass Tool Gateway.
