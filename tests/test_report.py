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
def test_error_report_not_scanned():
    assert build_report("j", "u", [], [], error="busy").automated_status == "not_scanned"
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
    assert "r0 — ` #x ` — WCAG 1.4.3" in t and "r4 — ` #x `" in t and "r5 — ` #x `" not in t
    assert "Keyboard: 12 focus stops walked, 1 keyboard issues" in t
    assert "r0" in t.split("Fixes")[1] and "fixed" in t
def test_error_only():
    t = render_chat(build_report("j", "u", [], [], error="timeout"))
    assert "timeout" in t and "NOT evaluated" not in t
BANNED = r"\b(pass|passed|compliant|certified|agent-ready)\b"
def strip_code(t):
    # Markdown-aware: remove fences, then inline spans, by their actual delimiter length
    t = re.sub(r"(?m)^(`{3,})\n.*?\n\1$", "", t, flags=re.S)
    return re.sub(r"(?<!`)(`+)(?!`) .*? \1(?!`)", "", t).replace("legal compliance certification", "")
def rep(sel="#x", diff="", error=None):
    f = Finding(rule_id="x", source="axe", status="fail", impact=None, selector=sel, wcag=["1.4.3"], message="m")
    return render_chat(build_report("j", "u", [] if error else [f], [], diff=diff, error=error))
def test_page_text_quoted():
    d = "<a class='agent-ready'>certified</a>"
    t = rep("#certified", d)
    assert "```\n" + d + "\n```" in t and "` #certified `" in t
    assert not re.search(BANNED, strip_code(t), re.I)
    e = rep(error="did not pass")
    assert "` did not pass `" in e and not re.search(BANNED, strip_code(e), re.I)
def test_embedded_backticks_in_error():
    e = rep(error="request ` certified ` failed")
    assert "certified" in e and not re.search(BANNED, strip_code(e), re.I)
def test_selector_with_double_backticks():
    t = rep("a``b certified ``c")
    assert "certified" in t and not re.search(BANNED, strip_code(t), re.I)
def test_diff_with_fence_line():
    d = "x\n```\n agent-ready \n```\ny"
    t = rep(diff=d)
    assert "````\n" + d + "\n````" in t
    assert not re.search(BANNED, strip_code(t), re.I)
def test_newline_in_inline_value():
    assert "a b" in rep("a\nb")
def test_needs_author_listed():
    t = render_chat(build_report("j", "u", [F("image-alt", "needs_author")], []))
    assert "image-alt" in t and "` #x `" in t
def test_cr_and_crlf_stay_in_span():
    for p in ("a\r\n\r\n# certified", "a\r\r# certified", "a\n\n# certified"):
        e = rep(error=p)
        assert "certified" in e and "\r" not in e.split("\n")[0] and len(e.split("\n")) == 2
        assert not re.search(BANNED, strip_code(e), re.I)
        t = rep(sel=p)
        assert "\r" not in t and not re.search(BANNED, strip_code(t), re.I)


def _tr(**kw):
    return render_chat(build_report("j", "u", [], ["1.4.3"]).copy(update=kw))
def test_tree_rendered_in_fence():
    tree = '- button "a ``` certified\r\n  agent-ready"'
    t = _tr(tree_before=tree)
    assert "What an AI agent sees (accessibility tree):" in t and "\r" not in t
    assert "````\n" in t and not re.search(BANNED, strip_code(t), re.I)
def test_fix_report_shows_before_and_after():
    t = _tr(tree_before="- button", tree_after='- button "Buy"', diff="d",
            fixes=[Fix(rule_id="a", selector="x", outcome="fixed", note="")])
    assert "Before:" in t and "After:" in t and "(page source, scripts off)" in t
def test_tree_truncated_in_chat():
    t = _tr(tree_before="x" * 1600)
    assert "(tree truncated at 1500 characters)" in t and "x" * 1501 not in t
def test_no_tree_no_section():
    assert "accessibility tree" not in _tr()
def test_delta_line_wording():
    from gate.models import Delta
    r = build_report("j", "u", [F("a")], ["1.4.3"]).copy(update={"delta": Delta(since="09:05 UTC 04 Nov", before=3, after=2, gone=2, new=1)})
    line = "Since your last scan of this URL (09:05 UTC 04 Nov): automated issues 3 → 2 (2 no longer detected, 1 new)"
    assert render_chat(r).splitlines()[1] == line and not re.search(BANNED, line, re.I)
