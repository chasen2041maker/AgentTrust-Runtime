from __future__ import annotations

import os
from pathlib import Path

import pytest

from agenttrust.permissions import PathSandbox
from agenttrust.schemas import ToolIntent


def _intent(path: str, tool_name: str = "read_file") -> ToolIntent:
    return ToolIntent(
        run_id="run",
        tool_call_id="call",
        tool_name=tool_name,
        arguments={"path": path, "content": "x"},
        source="test",
    )


def test_sandbox_allows_project_file(tmp_path: Path) -> None:
    decision = PathSandbox(tmp_path).check(_intent("README.md"))

    assert decision.effect == "allow"


def test_sandbox_denies_outside_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"

    decision = PathSandbox(tmp_path).check(_intent(str(outside)))

    assert decision.effect == "deny"
    assert decision.reason == "path escapes project_root"


def test_sandbox_denies_env_file(tmp_path: Path) -> None:
    decision = PathSandbox(tmp_path).check(_intent(".env"))

    assert decision.effect == "deny"
    assert decision.reason == "secret files are blocked"


def test_sandbox_denies_secret_paths_case_insensitively(tmp_path: Path) -> None:
    env_decision = PathSandbox(tmp_path).check(_intent(".ENV"))
    pem_decision = PathSandbox(tmp_path).check(_intent("cert.PEM"))
    ssh_decision = PathSandbox(tmp_path).check(_intent(".SSH/id_rsa"))

    assert env_decision.effect == "deny"
    assert pem_decision.effect == "deny"
    assert ssh_decision.effect == "deny"


@pytest.mark.skipif(os.name == "nt", reason="symlink behavior requires elevated Windows privileges")
def test_sandbox_denies_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    decision = PathSandbox(tmp_path).check(_intent("link.txt"))

    assert decision.effect == "deny"
    assert decision.reason == "path escapes project_root"
