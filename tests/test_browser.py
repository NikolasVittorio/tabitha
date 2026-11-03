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
        async with open_page(f"{http_server}/broken.html", allow_ips=LOCAL, max_bytes=10): pass
async def test_open_page_ok(http_server):
    async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL) as (page, html):
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
    async with open_page(f"{http_server}/sw.html", allow_ips=LOCAL) as (page, _):
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
    # page and each blob are under max_bytes, but 15 blobs exceed the 10 * max_bytes budget
    with pytest.raises(ValueError, match="too_large"):
        async with open_page(f"{http_server}/budget.html", allow_ips=LOCAL, max_bytes=2000): pass
async def test_dns_under_deadline(monkeypatch, http_server):
    monkeypatch.setattr(browser, "check_url", lambda *a: time.sleep(5))
    t = time.monotonic()
    with pytest.raises(TimeoutError):
        async with open_page(f"{http_server}/clean.html", allow_ips=LOCAL, timeout_s=1): pass
    assert time.monotonic() - t < 3
async def test_late_oversized_fetch_surfaces_on_exit(http_server):
    with pytest.raises(ValueError, match="too_large"):
        async with open_page(f"{http_server}/late.html", allow_ips=LOCAL, max_bytes=2000) as (page, _):
            await page.wait_for_timeout(1000)
import itertools
from conftest import HITS
from gate.browser import _context
BLOBS = lambda: [h for h in HITS if h.startswith("/blob.txt")]
async def test_budget_exact_boundary(http_server):
    # blob.txt is 1500 bytes; budget = 15000 = exactly 10 blobs, so the 11th+ must not be fetched
    HITS.clear()
    js = "(async()=>{for(let i=0;i<15;i++){await fetch('/blob.txt?'+i).catch(()=>{})}})()"
    with pytest.raises(ValueError, match="too_large"):
        async with _context(30, LOCAL, 1500) as (ctx, _):
            page = await ctx.new_page()
            await page.set_content(f'<base href="{http_server}/">')
            await page.evaluate(js)
    assert len(BLOBS()) == 10
async def test_concurrent_routes_no_fetch_after_exhaustion(http_server, monkeypatch):
    HITS.clear()
    calls = itertools.count()
    def slow_after_ten(*a):  # first 10 lookups instant, the rest still in DNS while the budget is spent
        if next(calls) >= 10: time.sleep(1)
    monkeypatch.setattr(browser, "check_url", slow_after_ten)
    imgs = "".join(f'<img src="/blob.txt?{i}">' for i in range(15))
    with pytest.raises(ValueError, match="too_large"):
        async with _context(30, LOCAL, 1500) as (ctx, _):
            page = await ctx.new_page()
            await page.set_content(f'<base href="{http_server}/">{imgs}')
    assert len(BLOBS()) == 10
async def test_late_too_large_wins_over_caller_exception_page(http_server):
    with pytest.raises(ValueError, match="too_large"):
        async with open_page(f"{http_server}/late.html", allow_ips=LOCAL, max_bytes=2000):
            await asyncio.sleep(1)
            raise RuntimeError("caller")
async def test_late_too_large_wins_over_caller_exception_html(http_server):
    html = f"<script>setTimeout(() => fetch('{http_server}/big.txt').catch(() => {{}}), 100)</script>"
    with pytest.raises(ValueError, match="too_large"):
        async with open_html(html, http_server, allow_ips=LOCAL, max_bytes=2000):
            await asyncio.sleep(1)
            raise RuntimeError("caller")
