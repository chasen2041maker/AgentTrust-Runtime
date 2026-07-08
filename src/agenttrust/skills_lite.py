"""Skill Lite local loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SkillInfo:
    name: str
    path: Path
    instruction: str
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "instruction_preview": self.instruction[:500],
            "allowed_tools": self.policy.get("allowed_tools", []),
            "blocked_tools": self.policy.get("blocked_tools", []),
            "required_fact_keys": self.policy.get("required_fact_keys", []),
            "output_contract": self.policy.get("output_contract", {}),
        }


def skills_root(project_root: Path) -> Path:
    return project_root / ".agenttrust" / "skills"


def list_skills(project_root: Path) -> list[str]:
    root = skills_root(project_root)
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and (path / "SKILL.md").exists())


def load_skill(project_root: Path, name: str) -> SkillInfo:
    path = skills_root(project_root) / name
    skill_path = path / "SKILL.md"
    if not skill_path.exists():
        raise ValueError(f"skill not found: {name}")
    policy_path = path / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise ValueError("skill policy must be a mapping")
    return SkillInfo(name=name, path=path, instruction=skill_path.read_text(encoding="utf-8"), policy=policy)


def ensure_demo_skill(project_root: Path) -> None:
    path = skills_root(project_root) / "code-review"
    path.mkdir(parents=True, exist_ok=True)
    skill_path = path / "SKILL.md"
    policy_path = path / "policy.yaml"
    if not skill_path.exists():
        skill_path.write_text("# Code Review\n\nReview diffs and report findings.\n", encoding="utf-8")
    if not policy_path.exists():
        policy_path.write_text(
            """name: code-review
allowed_tools:
  - read_file
  - git_diff
blocked_tools:
  - shell
  - write_file
required_fact_keys:
  - git_diff_files_changed
output_contract:
  required_sections:
    - findings
    - tests
    - risks
""",
            encoding="utf-8",
        )
