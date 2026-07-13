# AgentTrust Security Control Regression Suite

`security-v1` is a deterministic, local 107-check control regression suite: 100 expected-block attack cases and 7 expected-allow baselines. It never runs a supplied shell command or a user-configured MCP server. Its first drift case launches only a packaged fake stdio server to exercise the real fingerprint check. Scratch artifacts are kept under `.agenttrust/benchmarks/security-v1/` by default.

It is a deterministic security-control regression suite, not a penetration test or a production-safety guarantee.

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
