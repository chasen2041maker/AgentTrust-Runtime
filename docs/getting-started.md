# Getting Started

This guide gets AgentTrust Runtime from clone to first audited run.

## Install

```bash
git clone https://github.com/chasen2041maker/AgentTrust-Runtime.git
cd AgentTrust-Runtime
python -m pip install -e ".[test]"
```

## Initialize A Project

```bash
agenttrust init
```

This creates local runtime metadata:

```text
.agenttrust/
  policy.yaml
  runs/
  skills/code-review/
```

## Run The First Fact Gate

```bash
agenttrust run-fixture verified_answer
```

The command prints:

```text
run_id=<run_id>
run_dir=<path>
```

Replay the run:

```bash
agenttrust replay <run_id>
```

Generate a report:

```bash
agenttrust report <run_id>
agenttrust report <run_id> --format html
```

## Try The Failure Modes

Permission and sandbox:

```bash
agenttrust run-fixture blocked_secret
agenttrust run-fixture ask_noninteractive --non-interactive
```

GroundGuard coverage:

```bash
agenttrust run-fixture contradicted_answer
agenttrust run-fixture unverified_answer
```

MCP wrapper approval:

```bash
agenttrust run-fixture mcp_tool_denied --non-interactive
agenttrust run-fixture mcp_tool_approved --mode test
```

Recovery:

```bash
agenttrust run-fixture write_and_restore --mode test
agenttrust restore <run_id> --dry-run
agenttrust restore <run_id>
```

## Run Tests

```bash
python -m pytest
```

The suite covers the core runtime path plus MCP, Skill, Recovery, Hook, Memory, and Context Lite.
