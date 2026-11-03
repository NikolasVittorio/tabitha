from datetime import date
from gate.chat import parse_chat, Scan, Fix, Reply, USAGE
from gate.quota import Quota
D = date(2026, 11, 4)
def test_bare_url_scans():
    assert parse_chat("please check https://e.com/a", "s", Quota(), D) == Scan("https://e.com/a")
def test_fix_command():
    assert parse_chat("fix https://e.com", "s", Quota(), D) == Fix("https://e.com")
def test_no_url_or_bad_scheme_replies():
    for t in ["hello", "check file:///etc/passwd", "check javascript:alert(1)"]:
        assert parse_chat(t, "s", Quota(), D) == Reply(USAGE)
def test_quota():
    q = Quota(limit=5)
    for _ in range(5): assert isinstance(parse_chat("https://e.com", "s", q, D), Scan)
    assert isinstance(parse_chat("https://e.com", "s", q, D), Reply)
    assert isinstance(parse_chat("https://e.com", "other", q, D), Scan)
    assert isinstance(parse_chat("https://e.com", "s", q, date(2026, 11, 5)), Scan)  # new UTC day
def test_fix_charges_quota():
    from gate.chat import QUOTA_REPLY
    q = Quota(limit=5)
    for _ in range(5): assert isinstance(parse_chat("https://e.com", "s", q, D), Scan)
    assert parse_chat("fix https://e.com", "s", q, D) == Reply(QUOTA_REPLY)
def test_first_url_only():
    assert parse_chat("check https://a.com then http://b.com", "s", Quota(), D) == Scan("https://a.com")
