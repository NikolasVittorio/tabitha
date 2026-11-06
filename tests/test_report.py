import re

import pytest

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
def test_disclaimer_exact():
    r = build_report("j", "u", [F("a")], ["1.4.3", "2.4.2"])
    z = len(r.untested)
    assert r.disclaimer == (f"Automated scan result: 1 violations found across 2 tested WCAG 2.2 AA success criteria. {z} criteria require manual/human testing and were NOT evaluated. This is not a WCAG conformance determination or legal compliance certification. Suggested code changes are unreviewed and must be checked by a developer before use.")
    assert r.disclaimer in render_chat(r)
def test_sections():
    fs = [F(f"r{i}") for i in range(7)] + [F("kb", "fail", "walker"), F("rv", "needs_review")]
    r = build_report("j", "u", fs, ["1.4.3"], fixes=[Fix(rule_id="r0", selector="#x", outcome="fixed", note="n")], diff="D", focus_count=12)
    t = render_chat(r)
    assert t.startswith("**8 kinds of automated accessibility problem found, 8 places to change**\nPage: ` u `\n\nAutomated issues 8")
    assert ("\n\n**Fix these first**\n1. **m** (1 place)\n   What to do: Search for the rule name ` r0 ` to see how to fix it.\n"
            "   First one: ` #x `\n   (technical: r0, WCAG 1.4.3)\n2. **m** (1 place)") in t
    assert "5. **m** (1 place)\n   What to do: Search for the rule name ` r4 ` to see" in t and "` r5 `" not in t
    assert "- Plus 3 other kinds of problem. Fixing these and sending `recheck` will show them." in t
    assert "**Keyboard test:** 12 focus stops walked, 1 keyboard issue." in t
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
    t = rep("#certified")
    assert "` #certified `" in t
    assert not re.search(BANNED, strip_code(t), re.I)
    e = rep(error="did not pass")
    assert "` did not pass `" in e and not re.search(BANNED, strip_code(e), re.I)
def test_embedded_backticks_in_error():
    e = rep(error="request ` certified ` failed")
    assert "certified" in e and not re.search(BANNED, strip_code(e), re.I)
def test_selector_with_double_backticks():
    t = rep("a``b certified ``c")
    assert "certified" in t and not re.search(BANNED, strip_code(t), re.I)
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
    assert "(tree truncated at 600 characters)" in t and "x" * 601 not in t
def test_no_tree_no_section():
    assert "accessibility tree" not in _tr()
def test_delta_line_wording():
    from gate.models import Delta
    r = build_report("j", "u", [F("a")], ["1.4.3"]).copy(update={"delta": Delta(since="09:05 UTC 04 Nov", before=3, after=2, gone=2, new=1)})
    line = "Since your last scan of this URL (09:05 UTC 04 Nov): automated issues 3 → 2 (2 no longer detected, 1 new)"
    assert line in render_chat(r).splitlines() and not re.search(BANNED, line, re.I)
def _fx(*pairs, outcome="fixed"):
    return [Fix(rule_id=r, selector=s, outcome=outcome, note="") for r, s in pairs]
def _fixed_report(fixes, n=7):
    return render_chat(build_report("j", "u", [F(f"r{i}") for i in range(n)], ["1.4.3"], fixes=fixes, diff="d"))
def test_issues_left_line():
    t = _fixed_report(_fx(("r0", "#x"), ("r1", "#x"), ("r2", "#x"), ("r3", "#x")))
    line = "Automated issues 7 → 3 after fixes (4 fixed and re-checked on the page source with scripts off)"
    assert line in t.splitlines() and not re.search(BANNED, line, re.I)
def test_issues_left_none_fixed():
    t = _fixed_report(_fx(("r0", "#x"), outcome="not_fixed"))
    assert "No automated issue was fixed; see fix outcomes below" in t.splitlines() and "→" not in t
def test_issues_left_dedupes_pairs():
    assert "7 → 6 after fixes (1 fixed" in _fixed_report(_fx(("r0", "#x"), ("r0", "#x")))
def test_issues_left_ignores_uncounted_pairs():
    nr = Finding(rule_id="nr", source="axe", status="needs_review", impact=None, selector="#x", wcag=[], message="")
    r = build_report("j", "u", [F("r0"), F("r1"), nr], ["1.4.3"],
                     fixes=_fx(("r0", "#x"), ("nr", "#x"), ("ghost", "#y")), diff="d")
    assert "Automated issues 2 → 1 after fixes (1 fixed" in render_chat(r)
def test_issues_left_absent_without_fixes():
    assert "after fixes" not in render_chat(build_report("j", "u", [F("a")], ["1.4.3"]))
def test_new_since_last_scan_listed():
    from gate.models import Delta
    fs = [Finding(rule_id="r", source="axe", status="fail", impact=None, selector=s, wcag=["1.4.3"], message="m") for s in ("a", "b")]
    r = build_report("j", "u", fs, ["1.4.3"]).copy(update={"delta": Delta(since="x", before=1, after=2, gone=0, new=1, new_at=[1])})
    t = render_chat(r)
    lines = t.splitlines()
    i = lines.index("New since your last scan:")
    assert lines[i + 1] == "- r — ` b `" and "` a `" not in lines[i + 1] and not lines[i + 2].startswith("- ")
    assert not re.search(BANNED, strip_code(t), re.I)
def test_partial_scan_caveat_follows_since_line():
    from gate.models import Delta
    cav = ("Focus visibility was only partly checked on one of these scans (time limit), so focus issues can "
           "show as new or no longer detected for that reason alone.")
    d = Delta(since="x", before=3, after=2, gone=2, new=1, partial=True)
    t = render_chat(build_report("j", "u", [F("a")], ["1.4.3"]).copy(update={"delta": d}))
    assert cav in t.splitlines() and not re.search(BANNED, cav, re.I)
    t = render_chat(build_report("j", "u", [F("a")], ["1.4.3"]).copy(update={"delta": d.copy(update={"partial": False})}))
    assert "partly checked" not in t


def test_chat_names_the_agents_that_worked():
    from gate.models import Fix
    subs = {"scan": "agent1scan", "walk": "agent1walk", "fix": "agent1fix"}
    t = render_chat(build_report("j", "u", [], ["1.4.3"]), agents=subs)
    assert "Scanner ` agent1scan `" in t and "Walker ` agent1walk `" in t and "agent1fix" not in t  # a scan hires no fixer
    fixed = build_report("j", "u", [], ["1.4.3"], fixes=[Fix(rule_id="r", selector="s", outcome="fixed", note="")])
    assert "Fixer ` agent1fix `" in render_chat(fixed, agents=subs)
    assert "agent1scan" not in render_chat(build_report("j", "u", [], [], error="timeout"), agents=subs)  # nothing ran
    assert "Agents on this job" not in render_chat(build_report("j", "u", [], ["1.4.3"]))
def test_chat_leads_with_a_summary_and_groups_issues():
    def f(rule, impact, sel):
        return Finding(rule_id=rule, source="axe", status="fail", impact=impact, selector=sel, wcag=["1.4.3"], message=f"{rule} help.")
    fs = [f("minor-a", "minor", "#m")] + [f("many", "serious", f"#s{i}") for i in range(3)] + [f("worst", "critical", "#c")]
    t = render_chat(build_report("j", "https://e.com", fs, ["1.4.3"]).copy(update={"fixable": 2}))
    assert "for changes covering up to 2 of 5 issues (paid)" in t
    assert t.startswith("**3 kinds of automated accessibility problem found, 5 places to change**\nPage: ` https://e.com `\n\n**Fix these first**\n")
    assert t.index("1. **worst help**") < t.index("2. **many help**") < t.index("3. **minor-a help**")  # worst impact first
    assert ("2. **many help** (3 places)\n   What to do: Search for the rule name ` many ` to see how to fix it.\n"
            "   First one: ` #s0 `\n   (technical: many, WCAG 1.4.3)") in t and "#s1" not in t  # one example per kind
    assert "**Next:** send ` fix https://e.com `" in t and t.index("**Next:**") < t.index("**Not tested:**")
    assert not re.search(BANNED, strip_code(t), re.I)
def test_chat_next_step_follows_the_result():
    assert "**Next:** have a person test" in render_chat(build_report("j", "u", [], ["1.4.3"]))
    assert "**Next:** apply the changes below" in _fixed_report(_fx(("r0", "#x")))
def test_fixes_are_grouped_by_rule_and_outcome():
    t = _fixed_report(_fx(("r0", "#a"), ("r0", "#b")) + _fx(("r1", "#c"), outcome="regressed"))
    assert "- r0: fixed and re-checked (2)" in t and "- r1: dropped, it added a new failure (1)" in t
def test_long_selector_is_cut_in_chat():
    assert "s" * 81 not in rep("s" * 200) and "s" * 80 in rep("s" * 200)
def test_group_title_drops_detail_about_one_element():
    f = Finding(rule_id="focus", source="walker", status="fail", impact=None, selector="#a", wcag=["2.4.7"],
                message="No visible change on this element (Tab never reached it)")
    t = render_chat(build_report("j", "u", [f], ["2.4.7"]))
    assert "1. **No visible change on this element** (1 place)\n" in t and "(technical: focus, WCAG 2.4.7)" in t
    assert "Tab never reached it" not in t
def _paid_reply():
    fixes = [Fix(rule_id="button-name", selector="button", outcome="fixed", note="aria-label set; verify wording",
                 changes={"aria-label": "Buy `now`"}),
             Fix(rule_id="link-name", selector="a", outcome="needs_author", note="needs a name that says where /news goes")]
    return render_chat(build_report("j", "u", [F("a")], ["1.4.3"], fixes=fixes, diff="SECRET-DIFF"), agents={"scan": "agent1scan"})
def test_changes_replace_the_diff_in_chat():
    t = _paid_reply()
    assert "- ` button `: set `` aria-label = Buy `now` `` (verify wording)" in t
    assert "- ` a `: ` needs a name that says where /news goes `" in t and "SECRET-DIFF" not in t
def test_honest_parts_come_before_the_details():
    t = _paid_reply()
    assert t.index("**Not tested:**") < t.index("**Changes to make**") < t.index("Automated scan result") < t.index("Agents on this job")
def test_long_lists_are_capped():
    fixes = [Fix(rule_id="image-alt", selector=f"#i{n}", outcome="needs_author", note="n") for n in range(17)]
    t = render_chat(build_report("j", "u", [F("a")], ["1.4.3"], fixes=fixes))
    assert "#i9" in t and "#i10" not in t and "- Plus 7 more." in t
def test_paid_changes_are_not_cut_short():
    fixes = [Fix(rule_id="r", selector=f"#c{n}", outcome="fixed", note="n", changes={"a": "b"}) for n in range(40)]
    assert "#c39" in render_chat(build_report("j", "u", [F("a")], ["1.4.3"], fixes=fixes))
def test_no_paid_offer_when_a_patch_covers_nothing():
    t = render_chat(build_report("j", "https://e.com", [F("a")], ["1.4.3"]))
    assert "(paid)" not in t
    assert "**Next:** make the changes listed above, then send ` recheck https://e.com ` to see what is left." in t.splitlines()
def test_known_rule_gets_plain_words_and_the_exact_change():
    fs = [Finding(rule_id="image-alt", source="axe", status="needs_author", impact="critical", selector=f"img:nth-of-type({i})",
                  wcag=["1.1.1"], message="Images must have alternate text") for i in (1, 2)]
    t = render_chat(build_report("j", "u", fs, ["1.1.1"]))
    assert ("1. **Images have no text description** (2 places)\n"
            "   What to do: Add an `alt` attribute to each `<img>` that says what it shows, or `alt=\"\"` (empty on purpose) if it is only decoration.\n"
            "   First one: ` img:nth-of-type(1) `\n   (technical: image-alt, WCAG 1.1.1)") in t
    assert "Images must have alternate text" not in t
def test_note_sits_directly_under_the_head_once():
    note = "Large files on the page were not loaded (2 skipped), so anything they add or change on the page was not checked"
    t = render_chat(build_report("j", "https://e.com", [], ["1.4.3"]).copy(update={"note": note}))
    assert t.startswith(f"**No automated issues detected**\nPage: ` https://e.com `\nNote: {note}\n\n") and t.count("Note:") == 1
    assert "Note:" not in render_chat(build_report("j", "u", [], ["1.4.3"]))
def test_review_count_says_what_it_means():
    def reviews(n): return render_chat(build_report("j", "u", [F(f"r{i}", "needs_review") for i in range(n)], ["1.4.3"])).splitlines()
    assert "**Needs a person to review:** 13 things a person should check; a tool can't judge them." in reviews(13)
    assert "**Needs a person to review:** 1 thing a person should check; a tool can't judge it." in reviews(1)
def test_not_tested_gives_the_count_not_the_list():
    r = build_report("j", "u", [], ["1.4.3"])
    t = render_chat(r)
    assert f"**Not tested:** {len(r.untested)} criteria. A person needs to test these; an automated scan can't." in t.splitlines()
    assert "1.2.1" in r.untested and "1.2.1" not in t
def test_sections_run_from_what_to_change_to_what_was_not_tested():
    from gate.models import Delta
    r = build_report("j", "u", [F("a")], ["1.4.3"]).copy(update={"delta": Delta(since="x", before=1, after=1, gone=0, new=0)})
    t = render_chat(r)
    marks = ["**1 kind of automated accessibility problem found", "**Fix these first**", "Since your last scan", "**Keyboard test:**",
             "**Needs a person to review:**", "**Next:**", "**Not tested:**", "Automated scan result"]
    at = [t.index(m) for m in marks]
    assert at == sorted(at)
def test_too_large_error_says_what_happened_and_keeps_the_code():
    t = render_chat(build_report("j", "u", [], [], error="too_large")).splitlines()
    assert t[0] == ("The page's main HTML is over 2 MB, the limit Tabitha can load. Try a page with less HTML, or a lighter "
                    "section of the site. (code: ` too_large `)")
    assert t[1].startswith("Send `check <url>` for a free automated scan") and len(t) == 2
def test_unknown_error_code_gets_the_generic_sentence():
    t = render_chat(build_report("j", "u", [], [], error="weird_code")).splitlines()
    assert t[0] == "The scan did not complete, and Tabitha has no more detail. Try again in a minute. (code: ` weird_code `)"
@pytest.mark.parametrize("code", ["too_large", "timeout", "blocked", "scan_tampered", "internal_error", "bad_request",
                                  "quota_exceeded", "busy", "payment_required"])
def test_every_known_error_has_its_own_sentence_and_keeps_its_code(code):
    first = render_chat(build_report("j", "u", [], [], error=code)).splitlines()[0]
    assert first.endswith(f"(code: ` {code} `)") and "The scan did not complete" not in first and not first.startswith("Error")
    assert not re.search(BANNED, strip_code(first), re.I)
