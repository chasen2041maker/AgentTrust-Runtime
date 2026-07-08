"""GroundGuard-style fact mapping and verification adapter."""

from agenttrust.groundguard_adapter.mapper import Fact, map_tool_result, write_facts
from agenttrust.groundguard_adapter.verifier import CoverageReport, verify_answer, write_coverage_report

__all__ = [
    "CoverageReport",
    "Fact",
    "map_tool_result",
    "verify_answer",
    "write_coverage_report",
    "write_facts",
]
