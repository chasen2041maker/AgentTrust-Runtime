# Contributing

Contributions are welcome, especially small deterministic fixtures and security-oriented runtime checks.

## Good Contributions

- New fixtures that reproduce a concrete agent-tool failure.
- Better sandbox and permission tests.
- Additional fact mappers for explicit tool metadata.
- Documentation improvements that make the runtime easier to evaluate.
- MCP / Skill Lite examples from real local projects, with secrets removed.

## Development Setup

```bash
python -m pip install -e ".[test]"
python -m pytest
```

Run a few smoke paths before opening a larger change:

```bash
agenttrust init
agenttrust run-fixture verified_answer
agenttrust run-fixture mcp_tool_approved --mode test
agenttrust run-fixture write_and_restore --mode test
```

## Design Rules

- Keep the runtime local-first.
- Keep tests deterministic; do not require an LLM for CI.
- Route every tool source through `ToolIntent`.
- Do not let wrappers bypass permission, sandbox, trace, or fact mapping.
- Prefer explicit facts over automatic guessing from arbitrary raw output.

## Pull Request Checklist

- [ ] Tests pass with `python -m pytest`.
- [ ] New behavior has a fixture or focused unit test.
- [ ] Docs are updated when CLI behavior changes.
- [ ] No secrets, real customer data, or private paths are committed.
