import json
from datetime import datetime, timezone

import pytest

from gate.receipt import sign_receipt, verify_receipt
from gate.report import build_report

KEY = "11" * 32
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def _report():
    r = build_report("j", "https://e.com", [], ["1.4.3"])
    r.input_sha256 = "ab" * 32
    return r


def test_sign_verify_and_tamper():
    rc = sign_receipt(_report(), KEY, NOW)
    p = json.loads(rc.payload_json)
    assert p["title"] == "Automated Scan Log" and "NOT evaluated" in p["disclaimer"] and p["untested"]
    assert p["input_sha256"] == "ab" * 32 and p["timestamp"].startswith("2026-11-05")
    assert verify_receipt(rc)
    stripped = rc.copy(update={"payload_json": rc.payload_json.replace(p["disclaimer"], "")})
    assert not verify_receipt(stripped)
    assert not verify_receipt(rc.copy(update={"signature_hex": "zz"}))


def test_unbound_receipt_refused():
    r = build_report("j", "https://e.com", [], ["1.4.3"])
    with pytest.raises(ValueError):
        sign_receipt(r, KEY, NOW)
