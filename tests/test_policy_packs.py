from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttrust.adapters.policy.pack import export_policy_pack, import_policy_pack, load_policy_pack
from agenttrust.adapters.policy.yaml_policy import load_policy
from agenttrust.interfaces.cli import main


def _write_policy(path: Path) -> None:
    path.write_text(
        """policy_version: agenttrust.policy/v1
project_root: .
mode: locked
final_answer:
  on_incomplete: require_revision
verification:
  mode: groundguard_required
approvals:
  default_ttl_seconds: 120
rules:
  - id: ask-write
    tool: write_file
    paths: ["src/**"]
    effect: ask
    reason: review source writes
  - id: block-shell
    tool: shell
    argv_patterns:
      - ["rm", "**"]
    effect: deny
    reason: destructive shell
hooks:
  pre_tool:
    - id: block-doc-write
      when:
        tool: write_file
        path_glob: "docs/**"
      action: deny
      reason: documentation writes are reviewed separately
""",
        encoding="utf-8",
    )


def test_policy_pack_round_trip_uses_runtime_normalized_semantics(tmp_path: Path) -> None:
    source = tmp_path / "policy.yaml"
    pack_path = tmp_path / "packs" / "baseline.json"
    imported = tmp_path / "imported.yaml"
    _write_policy(source)

    exported = export_policy_pack(source, pack_path, name="baseline-controls", version="1.2.0")
    loaded = load_policy_pack(pack_path)
    imported_pack = import_policy_pack(pack_path, imported)

    assert exported == loaded == imported_pack
    assert loaded.digest.startswith("sha256:")
    assert loaded.policy.to_dict() == load_policy(imported).to_dict()
    assert loaded.policy.to_dict()["hooks"]["pre_tool"][0]["when"]["path_glob"] == "docs/**"


def test_policy_pack_rejects_tampering_unknown_fields_and_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "policy.yaml"
    pack_path = tmp_path / "baseline.json"
    target = tmp_path / "policy-target.yaml"
    _write_policy(source)
    export_policy_pack(source, pack_path, name="baseline-controls", version="1.2.0")

    raw = json.loads(pack_path.read_text(encoding="utf-8"))
    raw["policy"]["rules"][0]["effect"] = "allow"
    pack_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="digest does not match"):
        load_policy_pack(pack_path)

    export_policy_pack(source, pack_path, name="baseline-controls", version="1.2.0", overwrite=True)
    raw = json.loads(pack_path.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    pack_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported fields"):
        load_policy_pack(pack_path)

    export_policy_pack(source, pack_path, name="baseline-controls", version="1.2.0", overwrite=True)
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        import_policy_pack(pack_path, target)


def test_policy_pack_cli_exports_inspects_and_requires_explicit_import_overwrite(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    capsys.readouterr()

    assert main(
        [
            "policy",
            "export",
            ".agenttrust/policy.yaml",
            "--name",
            "local-baseline",
            "--version",
            "1.0.0",
            "--output",
            "policy-pack.json",
        ]
    ) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["pack"] == {"name": "local-baseline", "version": "1.0.0"}

    assert main(["policy", "inspect-pack", "policy-pack.json"]) == 0
    assert json.loads(capsys.readouterr().out)["policy_digest"] == exported["policy_digest"]

    imported_path = tmp_path / "imported.yaml"
    assert main(["policy", "import", "policy-pack.json", "--output", str(imported_path)]) == 0
    assert json.loads(capsys.readouterr().out)["output"] == str(imported_path)
    assert load_policy(imported_path).to_dict() == load_policy(tmp_path / ".agenttrust" / "policy.yaml").to_dict()

    assert main(["policy", "import", "policy-pack.json", "--output", str(imported_path)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert main(["policy", "import", "policy-pack.json", "--output", str(imported_path), "--force"]) == 0
