# AgentTrust Security Benchmark

`security-v1` is a deterministic, local 100-case adversarial benchmark. It never runs a supplied shell command and never starts an MCP server; each case directly exercises the runtime control that should block it. Scratch artifacts are kept under `.agenttrust/benchmarks/security-v1/` by default.

Run it from a project root:

```powershell
agenttrust benchmark security --output benchmark-report.json
```

The JSON report contains all public case IDs, expected outcomes, observed control decisions, and these aggregate metrics:

- `cases_total`
- `expected_blocks`
- `detected_blocks`
- `false_positives`
- `false_negatives`
- `critical_bypasses`
- `median_policy_latency_ms`

The versioned dataset has 100 attack cases: 20 path-sandbox, 10 secret-access, 20 shell-injection, 15 approval-bypass, 15 MCP trust/drift, 10 recovery-tampering, and 10 fact-contradiction cases. It also runs 7 expected-allow baselines, so false positives are measured rather than structurally zero. The first MCP drift case uses a packaged local stdio server and traverses the real command/schema fingerprint check; the rest make the drift-state transition deterministic. Definitions live in `src/agenttrust/benchmark/security.py`, so the public case set is versioned with the controls it verifies.
