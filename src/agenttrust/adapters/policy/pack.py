"""Portable, offline policy-pack import and export for policy protocol v1."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Mapping

import yaml

from agenttrust.adapters.policy.yaml_policy import load_policy
from agenttrust.domain.policy import Policy


POLICY_PACK_SCHEMA_VERSION = "agenttrust.policy-pack/v1"
_PACK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PACK_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


@dataclass(frozen=True)
class PolicyPack:
    """A normalized policy contract suitable for local review and exchange."""

    name: str
    version: str
    policy: Policy
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": POLICY_PACK_SCHEMA_VERSION,
            "pack": {"name": self.name, "version": self.version},
            "policy": self.policy.to_dict(),
            "policy_digest": self.digest,
        }


def export_policy_pack(
    policy_path: Path,
    output_path: Path,
    *,
    name: str,
    version: str,
    overwrite: bool = False,
) -> PolicyPack:
    """Write a normalized policy pack without silently replacing an artifact."""

    if not policy_path.exists():
        raise FileNotFoundError(f"policy file not found: {policy_path}")
    _validate_pack_identifier(name, version)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing policy pack: {output_path}")
    policy = load_policy(policy_path)
    pack = PolicyPack(name=name, version=version, policy=policy, digest=policy_pack_digest(policy.to_dict()))
    _write_atomic_json(output_path, pack.to_dict())
    return pack


def load_policy_pack(path: Path) -> PolicyPack:
    """Load and validate a policy pack before it can influence runtime policy."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"policy pack is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("policy pack must contain an object")
    allowed_fields = {"schema_version", "pack", "policy", "policy_digest"}
    unknown_fields = sorted(set(raw) - allowed_fields)
    if unknown_fields:
        raise ValueError(f"policy pack contains unsupported fields: {', '.join(unknown_fields)}")
    if raw.get("schema_version") != POLICY_PACK_SCHEMA_VERSION:
        raise ValueError(f"unsupported policy pack schema version: {raw.get('schema_version')}")
    pack_metadata = raw.get("pack")
    policy_payload = raw.get("policy")
    digest = raw.get("policy_digest")
    if not isinstance(pack_metadata, dict):
        raise ValueError("policy pack requires a pack object")
    name = pack_metadata.get("name")
    version = pack_metadata.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("policy pack name and version must be strings")
    _validate_pack_identifier(name, version)
    if not isinstance(policy_payload, dict):
        raise ValueError("policy pack requires a policy object")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ValueError("policy pack requires a sha256 policy_digest")
    policy = Policy.from_dict(policy_payload)
    normalized_policy = policy.to_dict()
    if policy_payload != normalized_policy:
        raise ValueError("policy pack policy must use the normalized AgentTrust policy v1 shape")
    expected_digest = policy_pack_digest(normalized_policy)
    if digest != expected_digest:
        raise ValueError("policy pack digest does not match its policy")
    return PolicyPack(name=name, version=version, policy=policy, digest=digest)


def import_policy_pack(pack_path: Path, output_path: Path, *, overwrite: bool = False) -> PolicyPack:
    """Validate a pack, then write its normalized YAML policy with explicit overwrite."""

    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing policy file: {output_path}")
    pack = load_policy_pack(pack_path)
    policy_text = yaml.safe_dump(pack.policy.to_dict(), allow_unicode=True, sort_keys=False)
    _write_atomic_text(output_path, policy_text)
    return pack


def policy_pack_digest(policy: Mapping[str, object]) -> str:
    """Return the digest of canonical normalized policy JSON, not YAML formatting."""

    return "sha256:" + sha256(_canonical_json(policy)).hexdigest()


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_pack_identifier(name: str, version: str) -> None:
    if not _PACK_NAME_PATTERN.fullmatch(name):
        raise ValueError("policy pack name must be 1-64 characters of letters, digits, dot, underscore, or hyphen")
    if not _PACK_VERSION_PATTERN.fullmatch(version):
        raise ValueError("policy pack version must be 1-64 characters of letters, digits, dot, plus, underscore, or hyphen")


def _write_atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_atomic_text(path, json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
