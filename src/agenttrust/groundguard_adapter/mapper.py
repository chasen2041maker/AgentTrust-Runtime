"""Compatibility exports for fact mapping."""

from agenttrust.adapters.verification.mapper import (
    Fact,
    explicit_fact_block_mapper,
    map_tool_result,
    tool_metadata_mapper,
    write_facts,
)


__all__ = ["Fact", "explicit_fact_block_mapper", "map_tool_result", "tool_metadata_mapper", "write_facts"]
