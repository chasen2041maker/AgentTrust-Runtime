from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from agenttrust.schemas import ToolIntent
from agenttrust.tools.git import git_diff


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_diff_reports_changed_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    tracked_file.write_text("before\nafter\n", encoding="utf-8")

    intent = ToolIntent(
        run_id="run_test",
        tool_call_id="call_001",
        tool_name="git_diff",
        arguments={},
        source="test",
    )
    result = git_diff(intent, tmp_path)

    assert result.status == "ok"
    assert result.metadata["files_changed"] == 1
    assert result.metadata["added_lines"] == 1
    assert result.metadata["deleted_lines"] == 0
    assert "+after" in result.output_preview
