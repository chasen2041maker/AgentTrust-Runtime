# CLI Reference

AgentTrust's CLI is organized around one local project directory. Use `--project-root` when you need to run commands outside the project root.

## Project Setup

```bash
agenttrust init
agenttrust policy validate .agenttrust/policy.yaml
```

## Fixtures

```bash
agenttrust fixtures
agenttrust run-fixture <name>
agenttrust run-fixture <name> --non-interactive
agenttrust run-fixture <name> --mode interactive|noninteractive|test
```

Useful fixtures:

| Fixture | What It Demonstrates |
| --- | --- |
| `blocked_secret` | Secret file read denied before execution. |
| `ask_noninteractive` | `ask` becomes `deny` in noninteractive mode. |
| `verified_answer` | Final answer is supported by recorded facts. |
| `contradicted_answer` | Final answer contradicts a recorded fact. |
| `unverified_answer` | Final answer omits required fact evidence. |
| `mcp_tool_denied` | MCP wrapper defaults to `ask`, then denies in noninteractive mode. |
| `mcp_tool_approved` | MCP wrapper executes after test-mode approval. |
| `skill_code_review` | Local skill policy allows `git_diff`. |
| `skill_blocked_tool` | Local skill policy blocks `shell`. |
| `write_and_restore` | `write_file` backup and restore path. |
| `blocked_by_hook` | `pre_tool` hook denies before sandbox/execution. |
| `memory_context_pack` | Memory and Context Lite artifacts. |

## Replay And Reports

```bash
agenttrust replay <run_id>
agenttrust report <run_id>
agenttrust report <run_id> --format html
```

## Tool Registry

```bash
agenttrust tools list
agenttrust tools inspect shell
agenttrust tools inspect mcp_tool
```

The registry exposes tool category, input schema, default permission effect, enabled state, and source.

## MCP Lite

```bash
agenttrust mcp inspect .mcp.json
```

The inspector supports common MCP config shapes, reads UTF-8 files with or without BOM, lists server names, commands, args, env keys, tool names, schema hashes, and a simple risk level. It never prints env values.

## Skill Lite

```bash
agenttrust skills list
agenttrust skills inspect code-review
agenttrust run --skill code-review "review this repository"
```

The built-in demo skill lives at:

```text
.agenttrust/skills/code-review/
  SKILL.md
  policy.yaml
```

`run --skill` is a Lite demo path. It loads the selected local skill and proves tool-scope enforcement with deterministic fixture execution.

## Recovery Lite

```bash
agenttrust restore <run_id>
agenttrust restore <run_id> --dry-run
agenttrust restore <run_id> --file src/app.py
```

Restore actions are also appended to the run trace. Existing files are restored from backup; files created by the run are deleted. Manifest paths are constrained to the project root and the run's `backups/` directory.

## Hook Lite

```bash
agenttrust hooks list
agenttrust run-fixture blocked_by_hook --mode test
```

Hooks run after the tentative permission decision and before sandboxing. They can only tighten the decision.

## Memory And Context Lite

```bash
agenttrust memory add project "GroundGuard verifies final numeric claims."
agenttrust memory add decision "Noninteractive ask is denied by default."
agenttrust memory list
agenttrust memory inspect
agenttrust memory clear --scope run

agenttrust context build --skill code-review
agenttrust context preview --skill code-review --budget 4000
agenttrust context export --run <run_id>
```

Context packs include project memory, decisions, selected skill instruction/policy, policy summary, selected tool schemas, and recent run summaries.
