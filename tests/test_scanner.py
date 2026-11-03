from gate.browser import open_page
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
