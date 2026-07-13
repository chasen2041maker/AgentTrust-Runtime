"""Append approval evidence events to each run's portable JSONL journal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


class JsonlApprovalJournal:
    """Mirror approval trace events into `.agenttrust/runs/{run_id}/approvals.jsonl`."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "approvals.jsonl"

    def append(self, event: Mapping[str, object]) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as approval_file:
            approval_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            approval_file.write("\n")
