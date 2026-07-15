"""Optional Ed25519 signatures for verified evidence trace heads.

The anchor remains a local artifact. A verifier must use a public key obtained
through an independent trusted channel to establish signer identity.
"""

from __future__ import annotations

import base64
import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from agenttrust.adapters.evidence.jsonl_store import verify_trace
from agenttrust.domain.models import utc_now_iso


ANCHOR_SCHEMA_VERSION = "agenttrust.evidence-anchor/v1"
ANCHOR_FILE_NAME = "trace-anchor.json"


def generate_signing_key_pair(
    private_key_path: Path,
    public_key_path: Path,
    *,
    passphrase: str,
) -> dict[str, str]:
    """Create a passphrase-encrypted Ed25519 private key and public key PEM."""

    if not passphrase:
        raise ValueError("a non-empty passphrase is required for evidence signing keys")
    if private_key_path.resolve() == public_key_path.resolve():
        raise ValueError("private and public key paths must be different")
    if private_key_path.exists() or public_key_path.exists():
        raise FileExistsError("refusing to overwrite an existing evidence signing key")

    serialization, private_key_type, _public_key_type, _invalid_signature = _crypto()
    private_key = private_key_type.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    _write_new_bytes(public_key_path, public_pem, mode=0o644)
    try:
        _write_new_bytes(private_key_path, private_pem, mode=0o600)
    except Exception:
        public_key_path.unlink(missing_ok=True)
        raise

    return {
        "private_key": str(private_key_path),
        "public_key": str(public_key_path),
        "key_id": _key_id(public_key, serialization),
    }


def sign_verified_trace(run_dir: Path, private_key_path: Path, *, passphrase: str) -> Path:
    """Sign the current, verified trace head and write ``trace-anchor.json``."""

    if not passphrase:
        raise ValueError("a non-empty passphrase is required for evidence signing")
    event_count, head_hash = _verified_head(run_dir)
    serialization, private_key_type, _public_key_type, _invalid_signature = _crypto()
    try:
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=passphrase.encode("utf-8"),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"unable to load evidence signing private key: {exc}") from exc
    if not isinstance(private_key, private_key_type):
        raise ValueError("evidence signing private key must be an Ed25519 key")

    public_key = private_key.public_key()
    payload = {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "run_id": run_dir.name,
        "event_count": event_count,
        "head_hash": head_hash,
        "signed_at": utc_now_iso(),
        "key_id": _key_id(public_key, serialization),
    }
    signature = private_key.sign(_canonical_json(payload))
    anchor = {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "payload": payload,
        "signature": {
            "algorithm": "ed25519",
            "value": base64.b64encode(signature).decode("ascii"),
            "public_key": public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii"),
        },
    }
    target = run_dir / ANCHOR_FILE_NAME
    _write_atomic_json(target, anchor)
    return target


def verify_trace_anchor(run_dir: Path, public_key_path: Path | None = None) -> dict[str, object]:
    """Verify an anchor signature and confirm it still matches the current trace head."""

    anchor_path = run_dir / ANCHOR_FILE_NAME
    try:
        raw_anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        payload, signature = _validated_anchor(raw_anchor)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _invalid_result("invalid_anchor", error=str(exc))
    if payload["run_id"] != run_dir.name:
        return _invalid_result("run_id_mismatch")

    serialization, _private_key_type, public_key_type, invalid_signature = _crypto()
    try:
        public_pem = public_key_path.read_bytes() if public_key_path is not None else signature["public_key"].encode("ascii")
        public_key = serialization.load_pem_public_key(public_pem)
    except (OSError, UnicodeEncodeError, ValueError) as exc:
        return _invalid_result("invalid_public_key", error=str(exc))
    if not isinstance(public_key, public_key_type):
        return _invalid_result("unsupported_public_key")
    if _key_id(public_key, serialization) != payload["key_id"]:
        return _invalid_result("public_key_id_mismatch")
    try:
        encoded_signature = base64.b64decode(signature["value"], validate=True)
        public_key.verify(encoded_signature, _canonical_json(payload))
    except (ValueError, invalid_signature):
        return _invalid_result("signature_invalid")

    verification = verify_trace(run_dir / "trace.jsonl")
    if verification.get("valid") is not True:
        return _invalid_result("trace_invalid", trace_reason=verification.get("reason"))
    if verification.get("event_count") != payload["event_count"] or verification.get("head_hash") != payload["head_hash"]:
        return _invalid_result("trace_head_changed")
    return {
        "valid": True,
        "run_id": payload["run_id"],
        "event_count": payload["event_count"],
        "head_hash": payload["head_hash"],
        "key_id": payload["key_id"],
        "signed_at": payload["signed_at"],
    }


def _verified_head(run_dir: Path) -> tuple[int, str | None]:
    verification = verify_trace(run_dir / "trace.jsonl")
    if verification.get("valid") is not True:
        raise ValueError(f"cannot sign invalid evidence trace: {verification.get('reason', 'unknown')}")
    event_count = verification.get("event_count")
    head_hash = verification.get("head_hash")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0:
        raise ValueError("evidence verification returned an invalid event count")
    if head_hash is not None and not isinstance(head_hash, str):
        raise ValueError("evidence verification returned an invalid head hash")
    return event_count, head_hash


def _validated_anchor(raw_anchor: object) -> tuple[dict[str, object], dict[str, str]]:
    if not isinstance(raw_anchor, dict) or raw_anchor.get("schema_version") != ANCHOR_SCHEMA_VERSION:
        raise ValueError(f"anchor must use {ANCHOR_SCHEMA_VERSION}")
    payload = raw_anchor.get("payload")
    signature = raw_anchor.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, dict):
        raise ValueError("anchor requires payload and signature objects")
    if payload.get("schema_version") != ANCHOR_SCHEMA_VERSION:
        raise ValueError("anchor payload schema version is invalid")
    for field_name in ("run_id", "signed_at", "key_id"):
        if not isinstance(payload.get(field_name), str) or not payload[field_name]:
            raise ValueError(f"anchor payload field '{field_name}' must be a non-empty string")
    event_count = payload.get("event_count")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0:
        raise ValueError("anchor payload event_count must be a non-negative integer")
    head_hash = payload.get("head_hash")
    if head_hash is not None and not isinstance(head_hash, str):
        raise ValueError("anchor payload head_hash must be a string or null")
    if signature.get("algorithm") != "ed25519":
        raise ValueError("anchor signature algorithm must be ed25519")
    for field_name in ("value", "public_key"):
        if not isinstance(signature.get(field_name), str) or not signature[field_name]:
            raise ValueError(f"anchor signature field '{field_name}' must be a non-empty string")
    return dict(payload), {"value": signature["value"], "public_key": signature["public_key"]}


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _key_id(public_key: Any, serialization: Any) -> str:
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return "sha256:" + sha256(public_der).hexdigest()


def _invalid_result(reason: str, **details: object) -> dict[str, object]:
    return {"valid": False, "reason": reason, **details}


def _write_new_bytes(path: Path, content: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write_atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _crypto() -> tuple[Any, Any, Any, Any]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError(
            "evidence signing requires the optional 'signing' dependency; install agenttrust-runtime[signing]"
        ) from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature
