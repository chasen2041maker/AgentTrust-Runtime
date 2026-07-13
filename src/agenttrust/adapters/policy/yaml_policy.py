"""YAML-backed policy loading adapter."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import yaml

from agenttrust.domain.policy import Policy


DEFAULT_POLICY_TEXT = """project_root: .
mode: default

final_answer:
  on_incomplete: warn

verification:
  mode: fallback

approvals:
  default_ttl_seconds: 3600

rules:
  - id: block-secret-files
    tool: read_file
    paths:
      - "**/.env"
      - ".env"
      - "**/*.pem"
      - "~/.ssh/**"
    effect: deny
    reason: "secret files are blocked"

  - id: deny-dangerous-shell
    tool: shell
    argv_patterns:
      - ["rm", "**", "/", "**"]
      - ["mkfs*", "**"]
      - ["sh", "**", "-c", "**"]
      - ["bash", "**", "-c", "**"]
      - ["zsh", "**", "-c", "**"]
      - ["dash", "**", "-c", "**"]
      - ["cmd", "**", "/c", "**"]
      - ["cmd.exe", "**", "/c", "**"]
      - ["powershell", "**", "-command", "**"]
      - ["pwsh", "**", "-command", "**"]
    effect: deny
    reason: "dangerous shell command"

  - id: ask-before-write-code
    tool: write_file
    paths:
      - "src/**"
      - "tests/**"
    effect: ask
    reason: "code changes require approval"

  - id: ask-before-mcp-tool
    tool: mcp_tool
    effect: ask
    reason: "MCP tool calls require approval"
"""


def load_policy(path: Path) -> Policy:
    """Load a YAML policy, using the local-first default when absent."""
    if not path.exists():
        return Policy.from_dict(yaml.safe_load(DEFAULT_POLICY_TEXT))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("policy file must contain a mapping")
    return Policy.from_dict(raw)


def snapshot_policy(path: Path, run_dir: Path) -> tuple[Path, str]:
    """Persist the exact policy text used by a run and return its version."""
    text = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_POLICY_TEXT
    snapshot = run_dir / "policy-snapshot.yaml"
    snapshot.write_text(text, encoding="utf-8", newline="\n")
    return snapshot, policy_digest(text.encode("utf-8"))


def policy_digest(policy_bytes: bytes) -> str:
    """Return the stable digest recorded as a policy snapshot version."""

    return "sha256:" + sha256(policy_bytes).hexdigest()
