from __future__ import annotations

import agenttrust.adapters.verification.verifier as verifier

from agenttrust.groundguard_adapter import map_tool_result, verify_answer
from agenttrust.schemas import ToolResult


def test_explicit_fact_block_maps_fact() -> None:
    result = ToolResult(
        run_id="run",
        tool_call_id="call",
        tool_name="shell",
        status="ok",
        output_preview="AGENTTRUST_FACTS:\nrevenue=3830000000 USD\nEND_AGENTTRUST_FACTS\n",
    )

    facts = map_tool_result(result)

    assert facts[0].key == "revenue"
    assert facts[0].value == "3830000000"
    assert facts[0].unit == "USD"


def test_verify_answer_detects_contradiction() -> None:
    result = ToolResult(
        run_id="run",
        tool_call_id="call",
        tool_name="shell",
        status="ok",
        output_preview="AGENTTRUST_FACTS:\nrevenue=3830000000 USD\nEND_AGENTTRUST_FACTS\n",
    )
    facts = map_tool_result(result)

    report = verify_answer("Revenue was $4.00 billion [fact:revenue].", facts, ["revenue"])

    assert report.status == "contradicted"
    assert report.contradicted_keys == ("revenue",)


def test_groundguard_required_never_silently_uses_the_fallback(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "FactGate", None)
    monkeypatch.setattr(verifier, "report_to_versioned_dict", None)
    result = ToolResult(
        run_id="run",
        tool_call_id="call",
        tool_name="shell",
        status="ok",
        output_preview="AGENTTRUST_FACTS:\nrevenue=42 USD\nEND_AGENTTRUST_FACTS\n",
    )

    report = verify_answer(
        "Revenue was 42 [fact:revenue].",
        map_tool_result(result),
        ["revenue"],
        verification_mode="groundguard_required",
    )

    assert report.status == "unverified"
    assert report.engine == "groundguard-required"
