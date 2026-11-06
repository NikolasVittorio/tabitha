from pathlib import Path

from gate.browser import open_html, open_page
from gate.fixer import fix
from gate.scanner import _dupes, aria_tree, scan

LOCAL = frozenset({"127.0.0.1"})


async def test_broken_page_rules(http_server):
    async with open_page(f"{http_server}/broken.html", allow_ips=LOCAL) as (page, _, _):
        findings, tested = await scan(page)
    ids = {f.rule_id for f in findings if f.status in ("fail", "needs_author")}
    assert {"html-has-lang", "color-contrast", "button-name", "image-alt"} <= ids
    assert "1.4.3" in tested
    cc = next(f for f in findings if f.rule_id == "color-contrast")
    assert "fgColor" in cc.data and "bgColor" in cc.data


async def test_clean_page_no_fails(http_server):
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, _, _):
        findings, _ = await scan(page)
    assert not [f for f in findings if f.status == "fail"]


async def test_forged_axe_accessor_ignored(http_server):
    async with open_page(f"{http_server}/attack.html", allow_ips=LOCAL) as (page, _, _):
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings}


async def test_csp_script_src_none_still_scans(http_server):
    async with open_page(f"{http_server}/csp.html", allow_ips=LOCAL) as (page, _, _):
        findings, _ = await scan(page)
    assert "color-contrast" in {f.rule_id for f in findings}


async def test_iframe_surfaces_as_needs_review(http_server):
    async with open_page(f"{http_server}/frame.html", allow_ips=LOCAL) as (page, _, _):
        findings, _ = await scan(page)
    ft = [f for f in findings if f.rule_id == "frame-tested"]
    assert ft and ft[0].status == "needs_review"


async def test_axe_configure_forgery_ignored(http_server):
    async with open_page(f"{http_server}/forge.html", allow_ips=LOCAL) as (page, _, _):
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings if f.status == "fail"}


async def test_shadow_target_is_nested_and_unfixable(http_server):
    async with open_page(f"{http_server}/shadow.html", allow_ips=LOCAL) as (page, html, _):
        findings, _ = await scan(page)
    bn = next(f for f in findings if f.rule_id == "button-name")
    assert bn.status == "needs_review" and bn.data["nested"] and bn.selector == "#host"
    _, fixes = fix(html, [bn])
    assert fixes[0].outcome == "not_fixed"


async def test_open_html_scans():
    async with open_html("<button></button>", "http://example.com/") as page:
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings}


async def test_open_html_blocks_page_scripts_even_with_meta_csp():
    # rescans are served under CSP script-src 'none'; a page meta CSP can only tighten it
    html = (Path(__file__).parent / "fixtures" / "broken.html").read_text("utf-8")
    html = ('<meta http-equiv="Content-Security-Policy" content="script-src \'unsafe-inline\' *">'
            + html + "<script>document.documentElement.dataset.js = 'ran'</script>"
            + '<img src="data:," onerror="document.documentElement.dataset.js = \'ran\'">')
    async with open_html(html, "http://example.com/x?a=1") as page:
        findings, _ = await scan(page)  # axe's isolated world is not subject to page CSP
        assert await page.get_attribute("html", "data-js") is None
        assert await page.evaluate("location.href") == "http://example.com/x?a=1"
    assert "button-name" in {f.rule_id for f in findings}



async def test_open_html_frame_cannot_cloak_parent(http_server):
    # a same-origin frame would get no CSP of its own; frame-src 'none' keeps it from loading
    html = '<html lang="en"><title>t</title><main><button id="v"></button><iframe src="/cloak-frame.html"></iframe></main>'
    async with open_html(html, f"{http_server}/x.html", allow_ips=LOCAL) as page:
        await page.wait_for_timeout(500)
        findings, _ = await scan(page)
    assert "button-name" in {f.rule_id for f in findings}


async def test_open_html_meta_refresh_cannot_replace_document(http_server):
    base = f"{http_server}/x.html"
    html = f'<meta http-equiv="refresh" content="0;url={http_server}/clean.html"><button></button>'
    async with open_html(html, base, allow_ips=LOCAL) as page:
        await page.wait_for_timeout(500)
        findings, _ = await scan(page)
        assert await page.evaluate("location.href") == base
    assert "button-name" in {f.rule_id for f in findings}


async def test_aria_tree_shows_names():
    async with open_html('<html lang="en"><body><button></button><button>Buy now</button></body></html>',
                         "http://127.0.0.1/") as page:
        t = await aria_tree(page)
    assert 'button "Buy now"' in t and t.count("- button") == 2


async def test_aria_tree_timeout_returns_empty():
    seen = {}

    class Loc:
        async def aria_snapshot(self, timeout=None):
            seen["timeout"] = timeout
            raise TimeoutError("stalled")

    class Page:
        def locator(self, _): return Loc()

    assert await aria_tree(Page()) == "" and seen["timeout"] == 5000


async def test_same_name_different_purpose(http_server):
    async with open_page(f"{http_server}/dupes.html", allow_ips=LOCAL) as (page, _, _):
        f, tested = await scan(page)
    d = {x.rule_id: x for x in f if x.source == "gate"}
    assert d["duplicate-link-name"].data["count"] == 3 and d["duplicate-link-name"].status == "needs_review"
    assert d["duplicate-link-name"].wcag == ["2.4.4"] and d["duplicate-button-name"].wcag == ["2.4.6"]
    assert d["duplicate-button-name"].data["count"] == 4
    assert sum(x.source == "gate" for x in f) == 2  # Home (same page) and Contact (unique) are not findings
    assert "Learn more" not in d["duplicate-link-name"].message  # no page text in messages


async def test_clean_page_has_no_duplicate_names(http_server):
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, _, _):
        f, _ = await scan(page)
    assert not any(x.source == "gate" for x in f)


async def test_dupes_evaluate_is_time_bounded():
    seen = {}

    class Cdp:
        async def send(self, method, params):
            seen.update(params)
            return {"result": {"type": "object"}, "exceptionDetails": {"text": "Script execution timed out."}}

    assert await _dupes(Cdp(), 1) == [] and seen["timeout"] == 5000  # CDP's own cap; the page cannot stall the scan


async def test_axe_string_data_does_not_crash_the_scan():
    html = ('<html lang="en"><head><title>t</title></head><body><main><p id="a">one</p><p id="a">two</p>'
            '<input aria-labelledby="a"></main></body></html>')
    async with open_html(html, "http://127.0.0.1:1/") as page:
        findings, _ = await scan(page)
    found = [f for f in findings if f.rule_id == "duplicate-id-aria"]
    assert found and found[0].data == {}


async def test_has_login_sees_a_password_field(http_server):
    from gate.scanner import has_login
    async with open_page(f"{http_server}/login.html", allow_ips=LOCAL) as (page, _, _):
        assert await has_login(page) is True
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, _, _):
        assert await has_login(page) is False


async def test_has_login_ignores_a_hidden_password_field():
    from gate.scanner import has_login
    hidden = ('<main><h1>News</h1><div style="display:none"><form><input type="password"></form></div></main>')
    async with open_html(hidden, "http://127.0.0.1:1/") as page:
        assert await has_login(page) is False
    shown = '<main><h1>Sign in</h1><form><input type="password"></form></main>'
    async with open_html(shown, "http://127.0.0.1:1/") as page:
        assert await has_login(page) is True
