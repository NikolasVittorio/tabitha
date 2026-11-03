from gate.allowlist import patch_violations, unparseable_style
from gate.fixer import fix
from gate.models import Finding

D = {"fgColor": "#999999", "bgColor": "#ffffff", "expectedContrastRatio": 4.5}


def test_style_comment_escape_quote_brace_payloads_untouched():
    for st in ('color:/*;display:none;*/#fff', 'd\\isplay:none',
               'color:&quot;foo;display:none;&quot;', "color:'foo;display:none;'",
               'color:{foo;display:none;}', 'color:url(x);margin:0'):
        html = f'<html><body><p style="{st}">Payment</p></body></html>'
        fnd = Finding(rule_id="color-contrast", source="axe", status="fail", impact=None, selector="p", wcag=[], message="", data=D)
        out, fixes = fix(html, [fnd])
        assert out == html and fixes[0].outcome == "not_fixed" and "unparseable" in fixes[0].note, st


def test_allowlist_flags_unparseable_before_or_after():
    a = '<p style="color:/*;display:none;*/#fff">x</p>'
    assert patch_violations(a, '<p style="display:none;*/#fff;color:#757575">x</p>')
    assert patch_violations('<p style="color:#fff">x</p>', a)


def test_plain_styles_parse():
    for ok in ("", "margin:0", "color:#fff;", "color: rgb(1, 2, 3); margin: 0 auto"):
        assert not unparseable_style(ok), ok


def test_unclosed_function_swallows_semicolon():
    # CSS keeps ";display:none" inside an unclosed function; a ";" split would activate it.
    for st in ("color:rgb(;display:none", "color:calc(1px;display:none", "color:var(--x;display:none"):
        html = f'<html><body><p style="{st}">Payment</p></body></html>'
        fnd = Finding(rule_id="color-contrast", source="axe", status="fail", impact=None, selector="p", wcag=[], message="", data=D)
        out, fixes = fix(html, [fnd])
        assert out == html and fixes[0].outcome == "not_fixed" and "unparseable" in fixes[0].note, st
        assert unparseable_style(st), st
        assert patch_violations(f'<p style="{st}">x</p>', '<p style="display:none;color:#757575">x</p>'), st


def test_plain_styles_still_simple():
    for ok in ("margin:0", "color:#999", "color: rgb(1, 2, 3)", "color:rgba(1,2,3,0.5)", "margin:0 auto;color:#999999"):
        assert not unparseable_style(ok), ok
