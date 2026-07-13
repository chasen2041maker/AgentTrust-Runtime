"""Compatibility exports for GroundGuard answer verification."""

from agenttrust.adapters.verification.verifier import CoverageReport, verify_answer, write_coverage_report

__all__ = ["CoverageReport", "verify_answer", "write_coverage_report"]
