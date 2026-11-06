import re
from datetime import date
import pytest
from gate.chat import parse_chat, Scan, Fix, Reply, USAGE, HELP
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

@pytest.mark.parametrize("text", [
    "fix example.com", "please fix example.com", "can you fix https://example.com?", "fix my site example.com",
    "Use Tabitha to fix this page: example.com"])
def test_a_request_to_fix_is_a_fix(text):
    assert isinstance(parse_chat(text, "s", Quota(), D), Fix)


@pytest.mark.parametrize("text", [
    "did the fix work? example.com", "does the fix work on example.com", "I pushed a fix, check example.com",
    "I already applied the fix on example.com", "has the fix landed? example.com", "Was the fix deployed? example.com"])
def test_a_question_about_a_fix_is_a_free_scan(text):
    q = Quota(limit=1)
    assert parse_chat(text, "s", q, D) == Scan("https://example.com")
    assert isinstance(parse_chat(text, "s", q, D), Reply)  # it charged the free scan quota


def test_question_words_inside_a_host_do_not_turn_a_fix_into_a_scan():
    assert parse_chat("fix https://did.example.com", "s", Quota(), D) == Fix("https://did.example.com")
    assert parse_chat("fix already.com", "s", Quota(), D) == Fix("https://already.com")


@pytest.mark.parametrize("text", ["help", "Help", "  COMMANDS ", "menu", "what can you do", "What can you do?",
                                  "how does this work", "how do I use this?"])
def test_help_is_free_and_never_reaches_the_model(text):
    q = Quota(limit=1)
    for _ in range(3):  # no quota is charged
        assert parse_chat(text, "s", q, D) == Reply(HELP)
    assert isinstance(parse_chat("check example.com", "s", q, D), Scan)


def test_help_only_when_it_is_the_whole_message():
    assert parse_chat("help me with my site", "s", Quota(), D) == Reply(USAGE)
    assert parse_chat("help example.com", "s", Quota(), D) == Scan("https://example.com")


def test_help_text():
    for part in ("check <url>", "recheck <url>", "fix <url>", "5 a day", "doesn't charge if nothing can be patched",
                 "One page at a time", "nothing behind a login"):
        assert part in HELP
    assert "http" not in HELP and "fetch1" not in HELP
    assert not re.search(r"(pass|passes|compliant|certified|accessible)", HELP, re.I)
