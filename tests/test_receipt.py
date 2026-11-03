import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gate.receipt import sign_receipt, verify_receipt
from gate.report import build_report

KEY = "11" * 32
OTHER = "22" * 32
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def _pub(key_hex):
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_hex)).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def _report():
    r = build_report("j", "https://e.com", [], ["1.4.3"])
    r.input_sha256 = "ab" * 32
    return r


def test_sign_verify_and_tamper():
    trusted = _pub(KEY)
    rc = sign_receipt(_report(), KEY, NOW)
    p = json.loads(rc.payload_json)
    assert p["title"] == "Automated Scan Log" and "NOT evaluated" in p["disclaimer"] and p["untested"]
    assert p["input_sha256"] == "ab" * 32 and p["timestamp"].startswith("2026-11-05")
    assert verify_receipt(rc, trusted)
    stripped = rc.copy(update={"payload_json": rc.payload_json.replace(p["disclaimer"], "")})
    assert not verify_receipt(stripped, trusted)
    assert not verify_receipt(rc.copy(update={"signature_hex": "zz"}), trusted)


def test_receipt_from_other_key_rejected():
    other_rc = sign_receipt(_report(), OTHER, NOW)
    assert verify_receipt(other_rc, _pub(OTHER))  # self-consistent
    assert not verify_receipt(other_rc, _pub(KEY))
    # attacker relabels the receipt with the trusted key: signature still fails
    assert not verify_receipt(other_rc.copy(update={"public_key_hex": _pub(KEY)}), _pub(KEY))


def test_unbound_receipt_refused():
    r = build_report("j", "https://e.com", [], ["1.4.3"])
    with pytest.raises(ValueError):
        sign_receipt(r, KEY, NOW)


def test_receipt_keeps_per_selector_outcomes():
    from gate.models import Fix
    a = Fix(rule_id="button-name", selector="#a", outcome="fixed", note="")
    b = Fix(rule_id="button-name", selector="#b", outcome="needs_author", note="")
    p1, p2 = (sign_receipt(_report().copy(update={"fixes": fx}), KEY, NOW).payload_json for fx in ([a, b], [b, a]))
    assert p1 == p2
    assert json.loads(p1)["fixes"] == [{"rule_id": "button-name", "selector": "#a", "outcome": "fixed"},
                                       {"rule_id": "button-name", "selector": "#b", "outcome": "needs_author"}]
