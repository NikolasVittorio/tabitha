import pytest
from gate.browser import check_url, open_page, open_html, Blocked
LOCAL = frozenset({"127.0.0.1"})
@pytest.mark.parametrize("u", ["file:///etc/passwd", "javascript:alert(1)", "http://169.254.169.254/", "http://10.0.0.1/", "http://localhost/"])
def test_check_url_blocks(u):
    with pytest.raises(Blocked):
        check_url(u)
def test_check_url_allow_ips():
    check_url("http://127.0.0.1/", LOCAL)
async def test_redirect_to_metadata_blocked(http_server):
    with pytest.raises(Blocked):
        async with open_page(f"{http_server}/redirect-metadata", allow_ips=LOCAL): pass
async def test_slow_page_times_out(http_server):
    with pytest.raises(TimeoutError):
        async with open_page(f"{http_server}/slow", allow_ips=LOCAL, timeout_s=2): pass
async def test_too_large(http_server):
    with pytest.raises(ValueError, match="too_large"):
        async with open_page(f"{http_server}/broken.html", allow_ips=LOCAL, max_bytes=10, main_max_bytes=10): pass
async def test_open_page_ok(http_server):
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, html, skipped):
        assert skipped == []
        assert "Clean page" in html
        assert await page.evaluate("document.documentElement.lang") == "en"
async def test_open_html_blocks_subresource():
    # base is a metadata address, so the relative image request must be aborted
    async with open_html('<img src="/x.png"><p>x</p>', "http://169.254.169.254/") as page:
        assert await page.inner_text("p") == "x"
        assert await page.evaluate("document.images[0].naturalWidth") == 0
import asyncio, socket, time
import gate.browser as browser
async def test_service_workers_blocked(http_server):
    async with open_page(f"{http_server}/sw.html", allow_ips=LOCAL) as (page, _, _):
        # blocked: register() is stubbed (resolves undefined) and no worker ever starts
        reg = await page.evaluate("navigator.serviceWorker.register('/sw.js').then(r => r ? 'registered' : 'stubbed')")
        await page.wait_for_timeout(500)
        assert reg == "stubbed" and page.context.service_workers == []
async def test_websocket_never_connects():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(); srv.setblocking(False)
    port = srv.getsockname()[1]
    try:
        async with open_html(f'<script>new WebSocket("ws://127.0.0.1:{port}")</script>', "http://example.com/", allow_ips=LOCAL) as page:
            await page.wait_for_timeout(1000)
        with pytest.raises(BlockingIOError):
            srv.accept()
    finally:
        srv.close()
async def test_job_byte_budget(http_server):
    # page and each blob are under max_bytes, but the 14th blob crosses the 10 * max_bytes budget and the 15th is
    # refused: the scan goes on without them
    async with open_page(f"{http_server}/budget.html", allow_ips=LOCAL, max_bytes=2000) as (page, html, skipped): pass
    assert "<title>b</title>" in html and len(skipped) == 2
async def test_dns_under_deadline(monkeypatch, http_server):
    monkeypatch.setattr(browser, "check_url", lambda *a: time.sleep(5))
    t = time.monotonic()
    with pytest.raises(TimeoutError):
        async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL, timeout_s=1): pass
    assert time.monotonic() - t < 3
async def test_late_oversized_fetch_is_skipped_not_fatal(http_server):
    async with open_page(f"{http_server}/late.html", allow_ips=LOCAL, max_bytes=2000) as (page, _, skipped):
        await page.wait_for_timeout(1000)
        assert await page.evaluate("document.title") == "l"
    assert len(skipped) == 1
import itertools
from conftest import HITS
from gate.browser import _context
BLOBS = lambda: [h for h in HITS if h.startswith("/blob.txt")]
async def test_budget_exact_boundary(http_server):
    # blob.txt is 1500 bytes; budget = 15000 = exactly 10 blobs, so the 11th+ must not be fetched
    HITS.clear()
    js = "(async()=>{for(let i=0;i<15;i++){await fetch('/blob.txt?'+i).catch(()=>{})}})()"
    async with _context(30, LOCAL, 1500) as (ctx, _, skipped):
        page = await ctx.new_page()
        await page.set_content(f'<base href="{http_server}/">')
        await page.evaluate(js)
    assert len(BLOBS()) == 10 and len(skipped) == 5
async def test_concurrent_routes_no_fetch_after_exhaustion(http_server, monkeypatch):
    HITS.clear()
    calls = itertools.count()
    def slow_after_ten(*a):  # first 10 lookups instant, the rest still in DNS while the budget is spent
        if next(calls) >= 10: time.sleep(1)
    monkeypatch.setattr(browser, "check_url", slow_after_ten)
    imgs = "".join(f'<img src="/blob.txt?{i}">' for i in range(15))
    async with _context(30, LOCAL, 1500) as (ctx, _, skipped):
        page = await ctx.new_page()
        await page.set_content(f'<base href="{http_server}/">{imgs}')
    assert len(BLOBS()) == 10 and len(skipped) == 5
BIGS = lambda: [h for h in HITS if h.startswith("/big.txt")]
async def test_oversized_files_still_spend_the_budget(http_server):
    # each 3000 byte big.txt is skipped against max_bytes 2000 but still adds its size to the 20000 budget: the 7th
    # takes it to 21000, so the other 8 requests are refused without a fetch
    HITS.clear()
    js = "(async()=>{for(let i=0;i<15;i++){await fetch('/big.txt?'+i).catch(()=>{})}})()"
    async with _context(30, LOCAL, 2000) as (ctx, _, skipped):
        page = await ctx.new_page()
        await page.set_content(f'<base href="{http_server}/">')
        await page.evaluate(js)
    assert len(BIGS()) == 7 and len(skipped) == 15
async def test_oversized_iframe_document_is_skipped(http_server):
    async with _context(30, LOCAL, 2000) as (ctx, blocked, skipped):
        page = await ctx.new_page()
        await page.set_content(f'<base href="{http_server}/"><iframe src="big.txt"></iframe><p>x</p>')
        assert await page.inner_text("p") == "x"
    assert len(skipped) == 1 and blocked == []
async def test_main_navigation_after_budget_spent_is_too_large(http_server):
    js = "(async()=>{for(let i=0;i<10;i++){await fetch('/blob.txt?'+i).catch(()=>{})}})()"
    with pytest.raises(ValueError, match="too_large"):
        async with _context(30, LOCAL, 1500) as (ctx, _, _):
            page = await ctx.new_page()
            await page.set_content(f'<base href="{http_server}/">')
            await page.evaluate(js)
            await page.goto(f"{http_server}/clean.html")
async def test_late_oversized_main_navigation_wins_over_caller_exception(http_server):
    with pytest.raises(ValueError, match="too_large"):
        async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL, max_bytes=2000, main_max_bytes=2000) as (page, _, _):
            await page.evaluate("setTimeout(() => { location = '/big.txt' }, 0)")
            await asyncio.sleep(1)
            raise RuntimeError("caller")
async def test_skipped_file_leaves_caller_exception_alone_page(http_server):
    with pytest.raises(RuntimeError, match="caller"):
        async with open_page(f"{http_server}/late.html", allow_ips=LOCAL, max_bytes=2000):
            await asyncio.sleep(1)
            raise RuntimeError("caller")
async def test_skipped_file_leaves_caller_exception_alone_html(http_server):
    # page scripts and re-navigation are off in open_html, so an oversized subresource is the way to skip one
    html = f'<img src="{http_server}/big.txt">'
    with pytest.raises(RuntimeError, match="caller"):
        async with open_html(html, http_server, allow_ips=LOCAL, max_bytes=2000):
            await asyncio.sleep(1)
            raise RuntimeError("caller")
@pytest.mark.parametrize("status", [403, 404, 500])
async def test_error_status_is_not_loaded(http_server, status):
    with pytest.raises(ValueError, match="not_loaded"):
        async with open_page(f"{http_server}/status/{status}", allow_ips=LOCAL): pass
@pytest.mark.parametrize("path", ["pixel.png", "data.json", "doc.pdf", "attachment"])
async def test_a_file_is_not_html(http_server, path):
    with pytest.raises(ValueError, match="not_html"):
        async with open_page(f"{http_server}/{path}", allow_ips=LOCAL): pass
async def test_blank_page_is_not_loaded_after_a_bounded_wait(http_server):
    t = time.monotonic()
    with pytest.raises(ValueError, match="not_loaded"):
        async with open_page(f"{http_server}/blank.html", allow_ips=LOCAL): pass
    assert 2.5 < time.monotonic() - t < 10
async def test_page_that_renders_late_is_not_blank(http_server):
    async with open_page(f"{http_server}/late-render.html", allow_ips=LOCAL) as (page, _, _):
        assert "Rendered late" in await page.inner_text("body")
@pytest.mark.parametrize("path", ["blocked-title.html", "blocked-heading.html"])
async def test_block_page_with_200_is_not_loaded(http_server, path):
    with pytest.raises(ValueError, match="not_loaded"):
        async with open_page(f"{http_server}/{path}", allow_ips=LOCAL): pass
async def test_article_about_access_denied_still_loads(http_server):
    async with open_page(f"{http_server}/article-access.html", allow_ips=LOCAL) as (page, _, _):
        assert "you have been blocked" in await page.inner_text("p")
async def test_login_page_still_opens(http_server):
    async with open_page(f"{http_server}/login.html", allow_ips=LOCAL) as (page, _, _):
        assert await page.locator("input[type=password]").count() == 1
async def test_main_document_may_be_bigger_than_other_files(http_server):
    # clean.html is a few hundred bytes: over max_bytes 100, under main_max_bytes 5000
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL, max_bytes=100, main_max_bytes=5000) as (page, html, _):
        assert "Clean page" in html
async def test_main_document_over_its_own_limit_is_too_large(http_server):
    with pytest.raises(ValueError, match="too_large"):
        async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL, max_bytes=5000, main_max_bytes=100): pass
async def test_other_files_keep_the_smaller_limit(http_server):
    # late.html asks for the 3000 byte big.txt: over max_bytes 2000, under main_max_bytes, so still skipped
    async with open_page(f"{http_server}/late.html", allow_ips=LOCAL, max_bytes=2000, main_max_bytes=5000) as (page, _, skipped):
        await page.wait_for_timeout(1000)
    assert len(skipped) == 1
