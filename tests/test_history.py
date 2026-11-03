from datetime import datetime, timezone
from gate.history import History
from gate.models import Delta, Finding
from gate.report import build_report
NOW = datetime(2026, 11, 4, 9, 5, tzinfo=timezone.utc)
def R(*sels, url="https://secret.example/p", error=None):
    fs = [Finding(rule_id="r", source="axe", status="fail", impact=None, selector=s, wcag=[], message="m") for s in sels]
    return build_report("j", url, fs, [], error=error)
def test_first_scan_no_delta():
    assert History().compare("s", "u", R("a"), NOW) is None
def test_delta_counts():
    h = History()
    h.compare("s", "u", R("a", "b", "c"), NOW)
    assert h.compare("s", "u", R("c", "d"), NOW) == Delta(since="09:05 UTC 04 Nov", before=3, after=2, gone=2, new=1)
def test_other_sender_gets_no_delta():
    h = History()
    h.compare("A", "u", R("a"), NOW)
    assert h.compare("B", "u", R("a"), NOW) is None
def test_error_report_ignored():
    h = History()
    h.compare("s", "u", R("a"), NOW)
    assert h.compare("s", "u", R(error="busy"), NOW) is None
    assert h.compare("s", "u", R("a"), NOW).before == 1  # the error stored nothing
def test_eviction_at_cap():
    h = History(max_entries=2)
    for u in "123":
        h.compare("s", u, R("a"), NOW)
    assert h.compare("s", "1", R("a"), NOW) is None
def test_stores_only_hashes():
    h = History()
    h.compare("sender-addr", "https://secret.example/p", R("#secret-sel"), NOW)
    s = repr(h.__dict__)
    assert not any(x in s for x in ("sender-addr", "secret.example", "secret-sel"))
def test_oversized_scan_not_stored():
    h = History()
    h.compare("s", "u", R("a"), NOW)
    assert h.compare("s", "u", R(*[f"#n{i}" for i in range(501)]), NOW) is None
    assert h.d == {}
    assert h.compare("s", "u", R("a"), NOW) is None
