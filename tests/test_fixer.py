from gate.models import Finding
from gate.fixer import fix
def f(rid, sel="html", data=None):
    return Finding(rule_id=rid, source="axe", status="fail", impact=None, selector=sel, wcag=[], message="", data=data or {})
def test_lang_and_button_and_alt():
    html = '<html><head></head><body><h1>Shop</h1><button title="Search"><svg></svg></button><img src="a.png"></body></html>'
    out, fixes = fix(html, [f("html-has-lang"), f("button-name", "button"), Finding(rule_id="image-alt", source="axe", status="needs_author", impact=None, selector="img", wcag=[], message="")])
    assert 'lang="en"' in out and 'aria-label="Search"' in out and "alt=" not in out
    assert {x.rule_id: x.outcome for x in fixes} == {"html-has-lang": "fixed", "button-name": "fixed", "image-alt": "needs_author"}
def test_rules_filter():
    out, fixes = fix('<html><body></body></html>', [f("html-has-lang")], rules=set())
    assert 'lang=' not in out and fixes == []
def test_title_and_contrast_and_unknown():
    html = '<html><head></head><body><h1>Shop</h1><p style="margin:0">hi</p></body></html>'
    d = {"fgColor": "#999999", "bgColor": "#ffffff", "expectedContrastRatio": "4.5:1"}
    out, fixes = fix(html, [f("document-title"), f("color-contrast", "p", d), f("region")])
    assert "<title>Shop</title>" in out and "margin:0" in out and "color:#" in out
    assert [x.outcome for x in fixes] == ["fixed", "fixed", "not_fixed"]
def test_duplicate_id_blocked_by_allowlist():
    out, fixes = fix('<html><body><i id="a"></i><b id="a"></b></body></html>', [f("duplicate-id", "b")])
    assert out.count('id="a"') == 2 and fixes[0].outcome == "not_fixed" and "id" in fixes[0].note
def test_missing_element():
    _, fixes = fix('<html><body></body></html>', [f("button-name", "button")])
    assert fixes[0].outcome == "not_fixed"
def test_duplicate_attrs_return_original_untouched():
    html = '<html><body><a href="/s" href="https://evil.example">Go</a></body></html>'
    out, fixes = fix(html, [f("html-has-lang")])
    assert out == html and fixes[0].outcome == "not_fixed"
def test_nothing_fixed_returns_original_string():
    html = '<html><body><img src=a.png></body></html>'
    out, _ = fix(html, [f("image-alt", "img")])
    assert out == html
