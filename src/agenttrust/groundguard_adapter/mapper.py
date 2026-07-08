"""Map ToolResult objects into structured facts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agenttrust.schemas import ToolResult


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    unit: str | None
    source_tool_call_id: str
    source_tool_name: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
            "source_tool_call_id": self.source_tool_call_id,
            "source_tool_name": self.source_tool_name,
        }


def explicit_fact_block_mapper(result: ToolResult) -> list[Fact]:
    facts: list[Fact] = []
    in_block = False
    for raw_line in result.output_preview.splitlines():
        line = raw_line.strip()
        if line == "AGENTTRUST_FACTS:":
            in_block = True
            continue
        if line == "END_AGENTTRUST_FACTS":
            in_block = False
            continue
        if not in_block or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        value = parts[0]
        unit = " ".join(parts[1:]) if len(parts) > 1 else None
        facts.append(
            Fact(
                key=key.strip(),
                value=value,
                unit=unit,
                source_tool_call_id=result.tool_call_id,
                source_tool_name=result.tool_name,
            )
        )
    return facts


def tool_metadata_mapper(result: ToolResult) -> list[Fact]:
    metadata = result.metadata
    facts: list[Fact] = []
    if result.tool_name == "read_file":
        if "bytes" in metadata:
            facts.append(_metadata_fact(result, "read_file_bytes", metadata["bytes"], "bytes"))
        if "lines" in metadata:
            facts.append(_metadata_fact(result, "read_file_lines", metadata["lines"], "count"))
        if result.output_digest:
            facts.append(_metadata_fact(result, "read_file_sha256", result.output_digest, None))
    elif result.tool_name == "git_diff":
        if "files_changed" in metadata:
            facts.append(_metadata_fact(result, "git_diff_files_changed", metadata["files_changed"], "count"))
        if "added_lines" in metadata:
            facts.append(_metadata_fact(result, "git_diff_added_lines", metadata["added_lines"], "count"))
        if "deleted_lines" in metadata:
            facts.append(_metadata_fact(result, "git_diff_deleted_lines", metadata["deleted_lines"], "count"))
    elif result.tool_name == "shell":
        if "exit_code" in metadata:
            facts.append(_metadata_fact(result, "shell_exit_code", metadata["exit_code"], "code"))
        if "duration_ms" in metadata:
            facts.append(_metadata_fact(result, "shell_duration_ms", metadata["duration_ms"], "ms"))
    return facts


def _metadata_fact(result: ToolResult, key: str, value: object, unit: str | None) -> Fact:
    return Fact(
        key=key,
        value=str(value),
        unit=unit,
        source_tool_call_id=result.tool_call_id,
        source_tool_name=result.tool_name,
    )


def map_tool_result(result: ToolResult) -> list[Fact]:
    if result.status != "ok":
        return []
    facts = explicit_fact_block_mapper(result)
    facts.extend(tool_metadata_mapper(result))
    return facts


def write_facts(path: Path, facts: list[Fact]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fact_file:
        for fact in facts:
            fact_file.write(json.dumps(fact.to_dict(), ensure_ascii=False, sort_keys=True))
            fact_file.write("\n")
