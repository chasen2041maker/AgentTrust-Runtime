# Contributing

Contributions are welcome when they strengthen a concrete, deterministic runtime control.

## Setup

```powershell
python -m pip install -e ".[test,otel]"
python -m pytest
ruff check src tests examples
mypy
```

## Good Contributions

- A minimal reproduction for an agent-tool security failure.
- A focused sandbox, approval, MCP, evidence or final-answer test.
- A framework integration that reuses the caller's session.
- A deterministic benchmark case with an explicit expected control outcome.
- Documentation that accurately describes observable runtime behavior.

## Rules

- Keep the runtime local-first and tests independent of LLM/API keys.
- Route every tool source through `ToolIntent` and the governed session path.
- Never let an adapter bypass permission, sandbox, evidence or fact mapping.
- Keep the domain free of concrete adapter imports.
- Do not commit secrets, private paths or real customer artifacts.

## Pull Request Checklist

- [ ] `python -m pytest` passes.
- [ ] Ruff and Mypy pass.
- [ ] New behavior has focused coverage or an explicit benchmark case.
- [ ] Docs and CLI help reflect behavior changes.
- [ ] Security-sensitive changes include a failure-mode test.
