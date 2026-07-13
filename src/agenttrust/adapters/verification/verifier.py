"""Deterministic structured fact coverage checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agenttrust.adapters.verification.mapper import Fact

try:  # pragma: no cover - exercised when GroundGuard is installed locally.
    from groundguard import FactGate, report_to_versioned_dict
except ImportError:  # pragma: no cover - fallback is tested in this package.
    FactGate = None  # type: ignore[assignment]
    report_to_versioned_dict = None  # type: ignore[assignment]


@dataclass(frozen=True)
class CoverageReport:
    status: str
    required_fact_keys: tuple[str, ...]
    engine: str = "agenttrust-fallback"
    verified_keys: tuple[str, ...] = ()
    contradicted_keys: tuple[str, ...] = ()
    unverified_keys: tuple[str, ...] = ()
    details: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "engine": self.engine,
            "required_fact_keys": list(self.required_fact_keys),
            "verified_keys": list(self.verified_keys),
            "contradicted_keys": list(self.contradicted_keys),
            "unverified_keys": list(self.unverified_keys),
            "details": list(self.details),
        }


def verify_answer(
    answer: str,
    facts: list[Fact],
    required_fact_keys: list[str],
    *,
    allow_simulated_facts: bool = False,
    verification_mode: str = "fallback",
) -> CoverageReport:
    if verification_mode not in {"fallback", "groundguard_required"}:
        raise ValueError(f"invalid verification mode: {verification_mode}")
    eligible_facts = facts if allow_simulated_facts else [fact for fact in facts if fact.trust_level == "trusted"]
    groundguard_report = _try_groundguard(answer, eligible_facts, required_fact_keys)
    if groundguard_report is not None:
        return groundguard_report
    if verification_mode == "groundguard_required":
        return CoverageReport(
            status="unverified",
            engine="groundguard-required",
            required_fact_keys=tuple(required_fact_keys),
            unverified_keys=tuple(required_fact_keys),
            details=tuple(
                {
                    "key": key,
                    "status": "unverified",
                    "reason": "GroundGuard verification was unavailable or invalid",
                }
                for key in required_fact_keys
            ),
        )
    return _fallback_verify_answer(answer, eligible_facts, required_fact_keys)


def _try_groundguard(answer: str, facts: list[Fact], required_fact_keys: list[str]) -> CoverageReport | None:
    if FactGate is None or report_to_versioned_dict is None:
        return None
    try:
        gate = FactGate(session_id="agenttrust")
        for fact in facts:
            gate.record_fact(
                key=fact.key,
                value=fact.value,
                unit=fact.unit,
                source_tool=fact.source_tool_name,
                source_call_id=fact.source_tool_call_id,
            )
        raw_report = gate.check(answer, required_fact_keys=required_fact_keys)
        payload = report_to_versioned_dict(raw_report)
    except Exception:
        return None

    claims = payload.get("claims", [])
    if not isinstance(claims, list) or not claims:
        return None

    omitted = payload.get("omitted_required_facts", [])
    omitted_keys = {
        str(item.get("key"))
        for item in omitted
        if isinstance(item, dict) and item.get("key") is not None
    }
    details_by_key: dict[str, dict[str, str]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        key = claim.get("fact_key") or claim.get("matched_fact_key")
        if key is None:
            continue
        claim_status = str(claim.get("status", "unverified"))
        details_by_key[str(key)] = {
            "key": str(key),
            "status": _normalize_groundguard_status(claim_status),
        }
        if claim.get("ledger_value") is not None:
            details_by_key[str(key)]["expected"] = str(claim["ledger_value"])
        if claim.get("answer_value") is not None:
            details_by_key[str(key)]["actual"] = str(claim["answer_value"])

    verified: list[str] = []
    contradicted: list[str] = []
    unverified: list[str] = []
    details: list[dict[str, str]] = []
    for key in required_fact_keys:
        key_status = details_by_key.get(key, {"key": key, "status": "unverified"})
        if key in omitted_keys:
            key_status = {"key": key, "status": "unverified", "reason": "required fact omitted"}
        details.append(key_status)
        if key_status["status"] == "contradicted":
            contradicted.append(key)
        elif key_status["status"] == "verified":
            verified.append(key)
        else:
            unverified.append(key)

    if contradicted:
        status = "contradicted"
    elif unverified:
        status = "unverified"
    else:
        status = "verified"
    return CoverageReport(
        status=status,
        engine="groundguard",
        required_fact_keys=tuple(required_fact_keys),
        verified_keys=tuple(verified),
        contradicted_keys=tuple(contradicted),
        unverified_keys=tuple(unverified),
        details=tuple(details),
    )


def _normalize_groundguard_status(status: str) -> str:
    if status == "verified":
        return "verified"
    if status == "contradicted":
        return "contradicted"
    return "unverified"


def _fallback_verify_answer(answer: str, facts: list[Fact], required_fact_keys: list[str]) -> CoverageReport:
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
        engine="agenttrust-fallback",
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
