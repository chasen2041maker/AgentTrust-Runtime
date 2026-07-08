"""Memory Lite explicit local memory store."""

from __future__ import annotations

import json
from pathlib import Path

from agenttrust.schemas import utc_now_iso


def memory_root(project_root: Path) -> Path:
    root = project_root / ".agenttrust" / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def add_memory(project_root: Path, scope: str, text: str) -> Path:
    root = memory_root(project_root)
    if scope == "project":
        path = root / "project.md"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"- {text}\n")
        return path
    if scope not in {"decision", "run"}:
        raise ValueError("memory scope must be project, decision, or run")
    path = root / ("decisions.jsonl" if scope == "decision" else "run-summaries.jsonl")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"created_at": utc_now_iso(), "text": text}, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return path


def append_run_summary(project_root: Path, summary: dict[str, object]) -> Path:
    root = memory_root(project_root)
    path = root / "run-summaries.jsonl"
    payload = {"created_at": utc_now_iso(), **summary}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return path


def list_memory(project_root: Path) -> dict[str, object]:
    root = memory_root(project_root)
    project = (root / "project.md").read_text(encoding="utf-8") if (root / "project.md").exists() else ""
    decisions = _read_jsonl(root / "decisions.jsonl")
    runs = _read_jsonl(root / "run-summaries.jsonl")
    return {"project": project, "decisions": decisions, "run_summaries": runs}


def clear_memory(project_root: Path, scope: str) -> None:
    root = memory_root(project_root)
    targets = {
        "project": [root / "project.md"],
        "decision": [root / "decisions.jsonl"],
        "run": [root / "run-summaries.jsonl"],
        "all": [root / "project.md", root / "decisions.jsonl", root / "run-summaries.jsonl"],
    }
    for path in targets.get(scope, []):
        if path.exists():
            path.unlink()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
