from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

from jsonschema import Draft202012Validator

from agenttrust.domain.models import ToolIntent
from agenttrust.domain.protocol import DecisionRequest
from agenttrust.tools.registry import get_tool_spec


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "conformance"
SCHEMAS = ROOT / "schemas"


def test_standalone_conformance_fixtures_validate_against_json_schemas() -> None:
    pairs = {
        "decision-request-v1.json": "decision-v1.schema.json",
        "policy-v1.json": "policy-v1.schema.json",
        "evidence-v1.json": "evidence-v1.schema.json",
        "tool-spec-v1.json": "tool-spec-v1.schema.json",
    }

    for fixture_name, schema_name in pairs.items():
        fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(fixture)


def test_runtime_protocol_objects_match_their_conformance_contracts() -> None:
    request = DecisionRequest.from_intent(
        ToolIntent("run", "call", "read_file", {"path": "README.md"}, "conformance")
    )

    assert request.to_dict()["protocol_version"] == "agenttrust.policy/v1"
    assert get_tool_spec("read_file").to_dict()["schema_version"] == "agenttrust.tool-spec/v1"


def test_built_distributions_include_every_protocol_schema(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(dist_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = {f"{name}" for name in ("decision-v1.schema.json", "policy-v1.schema.json", "evidence-v1.schema.json", "tool-spec-v1.schema.json")}
    wheel_path = next(dist_dir.glob("*.whl"))
    sdist_path = next(dist_dir.glob("*.tar.gz"))

    with zipfile.ZipFile(wheel_path) as wheel:
        wheel_schemas = {Path(name).name for name in wheel.namelist() if "/protocol_schemas/" in name}
    with tarfile.open(sdist_path) as sdist:
        sdist_schemas = {Path(member.name).name for member in sdist.getmembers() if "/schemas/" in member.name}

    assert expected <= wheel_schemas
    assert expected <= sdist_schemas
