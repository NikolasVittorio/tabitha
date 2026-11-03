import re
from gate.models import Finding, Fix
from gate.report import build_report, render_chat
F = lambda rid, st="fail", src="axe": Finding(rule_id=rid, source=src, status=st, impact="serious", selector="#x", wcag=["1.4.3"], message="m")
def test_clean_report_wording():
    r = build_report("j", "https://e.com", [], ["1.4.3"])
    assert r.automated_status == "no_automated_violations_detected"
    t = render_chat(r)
    assert "were NOT evaluated" in t and "not a WCAG conformance determination" in t
    assert not re.search(r"\b(pass|passed|compliant|certified|agent-ready)\b", t.replace("legal compliance certification", ""), re.I)
    assert str(len(r.untested)) in t
def test_violations_counted():
    r = build_report("j", "u", [F("color-contrast"), F("x", "needs_review")], ["1.4.3"])
    assert r.automated_status == "violations_found" and r.violation_count == 1
    assert build_report("j", "u", [F("image-alt", "needs_author")], []).violation_count == 1
def test_diff_truncated():
    r = build_report("j", "u", [], [], diff="x" * 9000)
    assert "truncated" in render_chat(r)
def test_disclaimer_exact():
    r = build_report("j", "u", [F("a")], ["1.4.3", "2.4.2"])
    z = len(r.untested)
    assert r.disclaimer == (f"Automated scan result: 1 violations found across 2 tested WCAG 2.2 AA success criteria. {z} criteria require manual/human testing and were NOT evaluated. This is not a WCAG conformance determination or legal compliance certification. Suggested code changes are unreviewed and must be checked by a developer before use.")
    assert r.disclaimer in render_chat(r)
def test_sections():
    fs = [F(f"r{i}") for i in range(7)] + [F("kb", "fail", "walker"), F("rv", "needs_review")]
    r = build_report("j", "u", fs, ["1.4.3"], fixes=[Fix(rule_id="r0", selector="#x", outcome="fixed", note="n")], diff="D", focus_count=12)
    t = render_chat(r)
    assert "r0 — #x — WCAG 1.4.3" in t and "r4 — #x" in t and "r5 — #x" not in t
    assert "Keyboard: 12 focus stops walked, 1 keyboard issues" in t
    assert "r0" in t.split("Fixes")[1] and "fixed" in t
def test_error_only():
    t = render_chat(build_report("j", "u", [], [], error="timeout"))
    assert "timeout" in t and "NOT evaluated" not in t
