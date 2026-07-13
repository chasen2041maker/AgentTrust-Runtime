"""Context Lite deterministic context pack builder."""

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

from agenttrust.memory_lite import list_memory
from agenttrust.adapters.policy.yaml_policy import load_policy
from agenttrust.skills_lite import load_skill
from agenttrust.tools.registry import list_tool_specs


def build_context_pack(project_root: Path, skill: str | None = None, budget: int = 4000) -> tuple[Path, Path]:
    out_dir = project_root / ".agenttrust" / "context"
    out_dir.mkdir(parents=True, exist_ok=True)
    sections: list[tuple[str, str]] = []
    memory = list_memory(project_root)
    selected_tools: list[str] | None = None
    sections.append(("project_memory", str(memory.get("project", ""))))
    sections.append(("decisions", json.dumps(memory.get("decisions", []), ensure_ascii=False, indent=2)))
    if skill:
        skill_info = load_skill(project_root, skill)
        selected_tools = [str(tool) for tool in skill_info.policy.get("allowed_tools", [])]
        sections.append(("skill", skill_info.instruction))
        sections.append(("skill_policy", json.dumps(skill_info.policy, ensure_ascii=False, indent=2)))
    policy = load_policy(project_root / ".agenttrust" / "policy.yaml")
    policy_text = (project_root / ".agenttrust" / "policy.yaml").read_text(encoding="utf-8")
    tool_specs = [spec.to_dict() for spec in list_tool_specs() if selected_tools is None or spec.name in selected_tools]
    sections.append(
        (
            "policy",
            json.dumps(
                {
                    "mode": policy.mode,
                    "rules": [rule.id for rule in policy.rules],
                    "hooks": [hook.id for hook in policy.hooks],
                },
                indent=2,
            ),
        )
    )
    sections.append(("tools", json.dumps(tool_specs, ensure_ascii=False, indent=2)))
    sections.append(("run_summaries", json.dumps(memory.get("run_summaries", []), ensure_ascii=False, indent=2)))

    included = []
    truncated = []
    remaining = budget
    lines = ["# AgentTrust Context Pack", ""]
    for name, content in sections:
        block = f"## {name}\n\n{content.strip()}\n\n"
        if len(block) > remaining:
            block = block[: max(0, remaining)]
            truncated.append(name)
        if block:
            lines.append(block)
            included.append(name)
            remaining -= len(block)
        if remaining <= 0:
            break
    pack_path = out_dir / "context-pack.md"
    manifest_path = out_dir / "context-manifest.json"
    pack_path.write_text("\n".join(lines), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "included_sections": included,
                "truncated_sections": truncated,
                "budget": budget,
                "included_skill": skill,
                "included_memory_keys": _memory_keys(memory),
                "included_tools": [str(spec["name"]) for spec in tool_specs],
                "included_recent_run_summaries": len(memory.get("run_summaries", [])),
                "policy_hash": "sha256:" + hashlib.sha256(policy_text.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return pack_path, manifest_path


def export_context_to_run(project_root: Path, run_id: str) -> tuple[Path, Path]:
    source_dir = project_root / ".agenttrust" / "context"
    run_dir = project_root / ".agenttrust" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pack_target = run_dir / "context-pack.md"
    manifest_target = run_dir / "context-manifest.json"
    shutil.copyfile(source_dir / "context-pack.md", pack_target)
    shutil.copyfile(source_dir / "context-manifest.json", manifest_target)
    return pack_target, manifest_target


def _memory_keys(memory: dict[str, object]) -> list[str]:
    keys = []
    if memory.get("project"):
        keys.append("project")
    if memory.get("decisions"):
        keys.append("decisions")
    if memory.get("run_summaries"):
        keys.append("run_summaries")
    return keys
