"""Deterministic structured fact coverage checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agenttrust.groundguard_adapter.mapper import Fact


@dataclass(frozen=True)
class CoverageReport:
    status: str
    required_fact_keys: tuple[str, ...]
    verified_keys: tuple[str, ...] = ()
    contradicted_keys: tuple[str, ...] = ()
    unverified_keys: tuple[str, ...] = ()
    details: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "required_fact_keys": list(self.required_fact_keys),
            "verified_keys": list(self.verified_keys),
            "contradicted_keys": list(self.contradicted_keys),
            "unverified_keys": list(self.unverified_keys),
            "details": list(self.details),
        }


def verify_answer(answer: str, facts: list[Fact], required_fact_keys: list[str]) -> CoverageReport:
    facts_by_key = {fact.key: fact for fact in facts}
    verified: list[str] = []
    contradicted: list[str] = []
    unverified: list[str] = []
    details: list[dict[str, str]] = []

    for key in required_fact_keys:
        fact = facts_by_key.get(key)
        marker = f"[fact:{key}]"
        if fact is None:
            unverified.append(key)
            details.append({"key": key, "status": "unverified", "reason": "required fact not recorded"})
            continue
        if marker not in answer:
            unverified.append(key)
            details.append({"key": key, "status": "unverified", "reason": "final answer does not cite required fact"})
            continue

        expected_number = _to_decimal(fact.value)
        answer_number = _extract_nearest_number(answer, marker)
        if expected_number is not None and answer_number is not None and expected_number != answer_number:
            contradicted.append(key)
            details.append(
                {
                    "key": key,
                    "status": "contradicted",
                    "expected": str(expected_number),
                    "actual": str(answer_number),
                }
            )
            continue

        verified.append(key)
        details.append({"key": key, "status": "verified", "value": fact.value})

    if contradicted:
        status = "contradicted"
    elif unverified:
        status = "unverified"
    else:
        status = "verified"

    return CoverageReport(
        status=status,
        required_fact_keys=tuple(required_fact_keys),
        verified_keys=tuple(verified),
        contradicted_keys=tuple(contradicted),
        unverified_keys=tuple(unverified),
        details=tuple(details),
    )


def write_coverage_report(path: Path, report: CoverageReport) -> None:
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def _extract_nearest_number(answer: str, marker: str) -> Decimal | None:
    before_marker = answer.split(marker, 1)[0]
    matches = list(re.finditer(r"\$?\b(\d+(?:\.\d+)?)\b\s*(billion|million|thousand)?", before_marker, re.IGNORECASE))
    if not matches:
        return None
    match = matches[-1]
    value = Decimal(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit == "billion":
        value *= Decimal("1000000000")
    elif unit == "million":
        value *= Decimal("1000000")
    elif unit == "thousand":
        value *= Decimal("1000")
    return value.normalize()
