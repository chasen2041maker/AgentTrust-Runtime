"""Map local tool results into structured verification facts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

from agenttrust.application.ports import EvidenceRecord
from agenttrust.domain.models import ToolResult


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
        facts.append(
            Fact(
                key=key.strip(),
                value=parts[0],
                unit=" ".join(parts[1:]) if len(parts) > 1 else None,
                source_tool_call_id=result.tool_call_id,
                source_tool_name=result.tool_name,
            )
        )
    return facts


def tool_metadata_mapper(result: ToolResult) -> list[Fact]:
    metadata = result.metadata
    facts: list[Fact] = []
    metric_keys = {
        "read_file": (("bytes", "read_file_bytes", "bytes"), ("lines", "read_file_lines", "count")),
        "git_diff": (
            ("files_changed", "git_diff_files_changed", "count"),
            ("added_lines", "git_diff_added_lines", "count"),
            ("deleted_lines", "git_diff_deleted_lines", "count"),
        ),
        "shell": (("exit_code", "shell_exit_code", "code"), ("duration_ms", "shell_duration_ms", "ms")),
    }
    for metadata_key, fact_key, unit in metric_keys.get(result.tool_name, ()):
        if metadata_key in metadata:
            facts.append(_metadata_fact(result, fact_key, metadata[metadata_key], unit))
    if result.tool_name == "read_file" and result.output_digest:
        facts.append(_metadata_fact(result, "read_file_sha256", result.output_digest, None))
    return facts


def map_tool_result(result: ToolResult) -> list[Fact]:
    if result.status != "ok":
        return []
    facts = explicit_fact_block_mapper(result)
    facts.extend(tool_metadata_mapper(result))
    return facts


def write_facts(path: Path, facts: Sequence[EvidenceRecord]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fact_file:
        for fact in facts:
            fact_file.write(json.dumps(fact.to_dict(), ensure_ascii=False, sort_keys=True))
            fact_file.write("\n")


def read_facts(path: Path) -> list[Fact]:
    """Load the structured fact ledger for a resumed session."""

    if not path.exists():
        return []
    facts: list[Fact] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("fact ledger entries must be objects")
        facts.append(
            Fact(
                key=_required_fact_text(raw, "key"),
                value=_required_fact_text(raw, "value"),
                unit=_optional_fact_text(raw, "unit"),
                source_tool_call_id=_required_fact_text(raw, "source_tool_call_id"),
                source_tool_name=_required_fact_text(raw, "source_tool_name"),
            )
        )
    return facts


def _metadata_fact(result: ToolResult, key: str, value: object, unit: str | None) -> Fact:
    return Fact(
        key=key,
        value=str(value),
        unit=unit,
        source_tool_call_id=result.tool_call_id,
        source_tool_name=result.tool_name,
    )


def _required_fact_text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"fact ledger requires a non-empty {key}")
    return value


def _optional_fact_text(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"fact ledger requires {key} to be a non-empty string or null")
    return value
