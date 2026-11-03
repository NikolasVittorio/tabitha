from gate.browser import open_html, open_page
from gate.fixer import fix
from gate.scanner import scan

LOCAL = frozenset({"127.0.0.1"})


async def test_broken_page_rules(http_server):
    async with open_page(f"{http_server}/broken.html", allow_ips=LOCAL) as (page, _):
        findings, tested = await scan(page)
    ids = {f.rule_id for f in findings if f.status in ("fail", "needs_author")}
    assert {"html-has-lang", "color-contrast", "button-name", "image-alt"} <= ids
    assert "1.4.3" in tested
    cc = next(f for f in findings if f.rule_id == "color-contrast")
    assert "fgColor" in cc.data and "bgColor" in cc.data


async def test_clean_page_no_fails(http_server):
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, _):
        findings, _ = await scan(page)
    assert not [f for f in findings if f.status == "fail"]


async def test_forged_axe_accessor_ignored(http_server):
    async with open_page(f"{http_server}/attack.html", allow_ips=LOCAL) as (page, _):
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings}


async def test_csp_script_src_none_still_scans(http_server):
    async with open_page(f"{http_server}/csp.html", allow_ips=LOCAL) as (page, _):
        findings, _ = await scan(page)
    assert "color-contrast" in {f.rule_id for f in findings}


async def test_iframe_surfaces_as_needs_review(http_server):
    async with open_page(f"{http_server}/frame.html", allow_ips=LOCAL) as (page, _):
        findings, _ = await scan(page)
    ft = [f for f in findings if f.rule_id == "frame-tested"]
    assert ft and ft[0].status == "needs_review"


async def test_axe_configure_forgery_ignored(http_server):
    async with open_page(f"{http_server}/forge.html", allow_ips=LOCAL) as (page, _):
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings if f.status == "fail"}


async def test_shadow_target_is_nested_and_unfixable(http_server):
    async with open_page(f"{http_server}/shadow.html", allow_ips=LOCAL) as (page, html):
        findings, _ = await scan(page)
    bn = next(f for f in findings if f.rule_id == "button-name")
    assert bn.status == "needs_review" and bn.data["nested"] and bn.selector == "#host"
    _, fixes = fix(html, [bn])
    assert fixes[0].outcome == "not_fixed"


async def test_open_html_scans():
    async with open_html("<button></button>", "http://example.com/") as page:
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings}
