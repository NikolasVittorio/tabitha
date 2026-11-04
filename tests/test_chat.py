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
def test_fix_is_paid_not_quota():
    q = Quota(limit=5)
    for _ in range(5): assert isinstance(parse_chat("https://e.com", "s", q, D), Scan)
    assert parse_chat("fix https://e.com", "s", q, D) == Fix("https://e.com")
def test_url_trailing_punctuation_and_markdown():
    assert parse_chat("check https://e.com/a.", "s", Quota(), D) == Scan("https://e.com/a")
    assert parse_chat("check (https://e.com/a)", "s", Quota(), D) == Scan("https://e.com/a")
    assert parse_chat("check [site](https://e.com/a)", "s", Quota(), D) == Scan("https://e.com/a")
def test_first_url_only():
    assert parse_chat("check https://a.com then http://b.com", "s", Quota(), D) == Scan("https://a.com")
def test_recheck_is_scan():
    assert parse_chat("recheck https://e.com", "s", Quota(), D) == Scan("https://e.com")
    assert "recheck <url>" in USAGE
def test_bare_domains():
    assert parse_chat("check example.com", "s", Quota(), D) == Scan("https://example.com")
    assert parse_chat("can you scan www.my-site.co.uk/pricing?", "s", Quota(), D) == Scan("https://www.my-site.co.uk/pricing")
    assert parse_chat("fix mysite.com", "s", Quota(), D) == Fix("https://mysite.com")
    assert parse_chat("recheck Example.COM.", "s", Quota(), D) == Scan("https://Example.COM")
def test_explicit_url_beats_bare_domain():
    assert parse_chat("check example.com via http://a.com", "s", Quota(), D) == Scan("http://a.com")
def test_fix_only_when_it_is_the_only_command_word():
    assert parse_chat("can you check and fix example.com", "s", Quota(), D) == Scan("https://example.com")
    assert parse_chat("please fix https://e.com", "s", Quota(), D) == Fix("https://e.com")
    assert parse_chat("I pushed a fix, recheck example.com", "s", Quota(), D) == Scan("https://example.com")
    assert parse_chat("FIX example.com", "s", Quota(), D) == Fix("https://example.com")
    # the rule gives Fix here: "fix" is the only command word, so a question that says "fix" is a paid fix
    assert parse_chat("did the fix work? example.com", "s", Quota(), D) == Fix("https://example.com")
def test_command_word_in_a_second_url_host_is_not_a_command():
    assert parse_chat("see https://a.com and https://fix.com", "s", Quota(), D) == Scan("https://a.com")
def test_bare_domain_keeps_port_and_query():
    assert parse_chat("check example.com:8080/x?y=1", "s", Quota(), D) == Scan("https://example.com:8080/x?y=1")
    assert parse_chat("check example.com?y=1", "s", Quota(), D) == Scan("https://example.com?y=1")
    assert parse_chat("is example.com?", "s", Quota(), D) == Scan("https://example.com")
    assert parse_chat("check example.com: it is slow", "s", Quota(), D) == Scan("https://example.com")
def test_not_domains():
    for t in ["mail me@site.com", "check index.html", "see e.g. the docs", "check app.js and style.css"]:
        assert parse_chat(t, "s", Quota(), D) == Reply(USAGE)
def test_command_word_inside_the_url_is_not_a_command():
    assert parse_chat("fix.com", "s", Quota(), D) == Scan("https://fix.com")
