from __future__ import annotations

from pathlib import Path

from agenttrust.interfaces.python_api import AgentTrustRuntime


def test_python_sdk_executes_through_governed_pipeline(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("sdk\n", encoding="utf-8")

    result = AgentTrustRuntime(tmp_path, runtime_mode="test").execute("read_file", {"path": "README.md"})

    assert result.outcome.result is not None
    assert result.outcome.result.status == "ok"
    assert (result.run_dir / "trace.jsonl").exists()
    assert (result.run_dir / "policy-snapshot.yaml").exists()
