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
