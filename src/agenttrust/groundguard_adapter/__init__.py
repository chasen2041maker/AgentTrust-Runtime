"""GroundGuard-style fact mapping and verification adapter."""

from agenttrust.adapters.verification.mapper import Fact, map_tool_result, read_facts, write_facts
from agenttrust.adapters.verification.verifier import CoverageReport, verify_answer, write_coverage_report

__all__ = [
    "CoverageReport",
    "Fact",
    "map_tool_result",
    "read_facts",
    "verify_answer",
    "write_coverage_report",
    "write_facts",
]
