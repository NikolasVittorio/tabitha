from gate.allowlist import patch_violations
from gate.fixer import fix
from gate.models import Finding

D = {"fgColor": "#999999", "bgColor": "#ffffff", "expectedContrastRatio": 4.5}


def test_style_comment_and_escape_payloads_untouched():
    for st in ('color:/*;display:none;*/#fff', 'd\\isplay:none'):
        html = f'<html><body><p style="{st}">Payment</p></body></html>'
        fnd = Finding(rule_id="color-contrast", source="axe", status="fail", impact=None, selector="p", wcag=[], message="", data=D)
        out, fixes = fix(html, [fnd])
        assert out == html and fixes[0].outcome == "not_fixed" and "unparseable" in fixes[0].note


def test_allowlist_flags_unparseable_before_or_after():
    a = '<p style="color:/*;display:none;*/#fff">x</p>'
    assert patch_violations(a, '<p style="display:none;*/#fff;color:#757575">x</p>')
    assert patch_violations('<p style="color:#fff">x</p>', a)
