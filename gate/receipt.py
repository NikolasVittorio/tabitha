import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from gate.models import Receipt, Report


def sign_receipt(r: Report, key_hex: str, now: datetime) -> Receipt:
    # ponytail: signer hashes nothing; Task 9 fills input_sha256 from the pre-patch HTML.
    if not r.input_sha256:
        raise ValueError("input_sha256 required: refusing to issue an unbound receipt")
    payload = json.dumps({
        "title": "Automated Scan Log",
        "scope": "valid for this exact input at this time only",
        "url": r.url,
        "input_sha256": r.input_sha256,
        "timestamp": now.astimezone(timezone.utc).isoformat(),
        "engine": "axe-core 4.14.0 + a11y-gate walker v1",
        "automated_status": r.automated_status,
        "violation_count": r.violation_count,
        "fixes": {f.rule_id: f.outcome for f in r.fixes},
        "untested": r.untested,
        "disclaimer": r.disclaimer,
    }, sort_keys=True, separators=(",", ":"))
    sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_hex))
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return Receipt(payload_json=payload, signature_hex=sk.sign(payload.encode()).hex(), public_key_hex=pub.hex())


def verify_receipt(rc: Receipt) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(rc.public_key_hex)).verify(
            bytes.fromhex(rc.signature_hex), rc.payload_json.encode())
        return True
    except (InvalidSignature, ValueError):
        return False
