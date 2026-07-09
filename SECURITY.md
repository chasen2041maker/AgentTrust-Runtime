# Security Policy

AgentTrust Runtime is a local-first project. It does not upload run artifacts by default, but those artifacts can contain sensitive paths, tool output, prompt text, and structured facts.

## Reporting Security Issues

Please open a private report or contact the maintainer before publishing details for issues such as:

- path sandbox bypasses;
- secret-file access bypasses;
- restore writing outside the project root;
- MCP wrapper calls bypassing permission checks;
- trace/report output leaking secrets unexpectedly.

## Current Security Scope

Covered controls:

- policy-based `allow` / `ask` / `deny`;
- noninteractive `ask -> deny`;
- tool-registry default-effect fallback;
- path sandbox checks for project root, system paths, and common secret files;
- skill-scope enforcement;
- pre-tool hooks that can only tighten decisions;
- restore constraints for project-root targets and run-local backups;
- GroundGuard-backed final-answer fact verification.

Out of scope:

- remote MCP proxying;
- network egress control;
- cloud policy management;
- tamper-evident audit logs;
- full OWASP Agentic Top 10 coverage;
- universal hallucination detection.

## Artifact Hygiene

Before sharing `.agenttrust/runs/`, reports, screenshots, or fixture data, review and redact:

- prompts;
- tool output;
- file paths;
- environment variable names;
- business metrics;
- personal or customer data.
