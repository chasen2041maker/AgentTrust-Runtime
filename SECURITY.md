# Security Policy

AgentTrust Runtime is local-first. It does not upload run artifacts by default, but local evidence may include prompts, paths, tool output and structured facts.

## Reporting

Please report suspected vulnerabilities privately before public disclosure, especially for:

- path sandbox or secret-file bypasses;
- noninteractive approval or argument-digest bypasses;
- MCP consent, tool trust or schema-drift bypasses;
- recovery writes outside project/run backup boundaries;
- evidence-chain verification or state-rebuild bypasses;
- unexpected artifact or environment-value disclosure.

## Current Controls

- Unknown tools fail closed and risky built-ins default to `ask`.
- Safe shell execution accepts argv with `shell=False`; dangerous compatibility behavior is explicit.
- Path sandboxing blocks project escapes, system paths and common secret locations.
- Persisted approvals bind a tool call's argument digest and are rechecked on resume.
- MCP starts only after consent; real tools require trust and unchanged fingerprints.
- JSONL evidence is hash-linked, independently verifiable and used as the source for SQLite rebuild.
- Final-answer facts are scoped to the current session and checked by GroundGuard.

Run `agenttrust benchmark security --output benchmark-report.json` to execute the public deterministic control regression suite.

## Residual Risk

AgentTrust cannot secure tools that bypass its gateway, prove a model's intent, provide network egress sandboxing, or guarantee that local artifacts contain no sensitive data. Before sharing `.agenttrust/runs/`, inspect and redact prompts, paths, tool outputs, business metrics and personal data.
