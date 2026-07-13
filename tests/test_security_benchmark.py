"""Tests for the public deterministic AgentTrust security benchmark."""

from __future__ import annotations

import json

from agenttrust.benchmark.security import CATEGORY_COUNTS, run_security_benchmark, security_cases
from agenttrust.cli import main


def test_public_security_dataset_has_one_hundred_attack_cases_and_safe_baselines() -> None:
    cases = security_cases()

    attack_cases = [case for case in cases if case.expected_block]
    assert len(cases) == 107
    assert len(attack_cases) == 100
    assert len({case.case_id for case in cases}) == 107
    assert {category: sum(case.category == category for case in cases) for category in CATEGORY_COUNTS} == CATEGORY_COUNTS
    assert all(case.expected_block for case in attack_cases)


def test_security_benchmark_detects_every_expected_attack(tmp_path) -> None:
    report = run_security_benchmark(tmp_path)

    assert report.cases_total == 107
    assert report.expected_blocks == 100
    assert report.detected_blocks == 100
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.critical_bypasses == 0
    assert report.median_policy_latency_ms >= 0
    assert all(result.detected_block for result in report.results if result.case.expected_block)
    assert not any(result.detected_block for result in report.results if not result.case.expected_block)
    real_drift = next(result for result in report.results if result.case.case_id == "mcp-trust-drift-01")
    assert real_drift.detected_block is True
    assert real_drift.detail == "tool_schema_changed"


def test_security_benchmark_cli_writes_reproducible_json_report(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["benchmark", "security", "--output", "benchmark-report.json"]) == 0

    output = capsys.readouterr().out
    report_path = tmp_path / "benchmark-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert str(report_path) in output
    assert report["dataset_version"] == "security-v1"
    assert report["cases_total"] == 107
    assert len(report["results"]) == 107
