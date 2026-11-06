"""SSRF-guarded Playwright openers. The only path that loads untrusted pages."""
import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError, async_playwright


class Blocked(Exception):
    pass


def _is_main_doc(req) -> bool:
    try:
        return req.is_navigation_request() and req.frame.parent_frame is None
    except PlaywrightError:  # a request with no frame (a worker's) is never the page's document
        return False


def check_url(url: str, allow_ips: frozenset[str] = frozenset()) -> None:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise Blocked("scheme")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise Blocked("unresolvable")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        # IPv4-mapped IPv6 (::ffff:10.0.0.1) must be judged as the IPv4 address
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if str(ip) in allow_ips:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified or not ip.is_global):
            raise Blocked("private_address")


@asynccontextmanager
async def _context(timeout_s, allow_ips, max_bytes, *, main_max_bytes=None):
    """Fresh browser+context with the guard installed; yields (context, blocked, skipped).
    The page's own document may be main_max_bytes (default max_bytes); every other file is held to max_bytes.
    blocked holds "too_large" only for the page's own document, which ends the job. Any other oversized or over-budget
    request is aborted and added to skipped, so the page keeps running and the scan keeps its results."""
    blocked: list[str] = []
    skipped: list[str] = []
    total = 0

    async def guard(route):
        nonlocal total
        url, kw = route.request.url, {}
        main = _is_main_doc(route.request)
        limit = (main_max_bytes or max_bytes) if main else max_bytes

        async def refuse():
            (blocked if main else skipped).append("too_large")
            await route.abort("blockedbyclient")

        try:
            # Chromium follows redirects of routed requests internally, unchecked. So fetch
            # with max_redirects=0 and follow hops here, checking every hop.
            for _ in range(10):
                if total >= 10 * max_bytes:  # budget spent: fetch nothing more
                    return await refuse()
                # getaddrinfo blocks, keep it off the event loop
                await asyncio.to_thread(check_url, url, allow_ips)
                if total >= 10 * max_bytes:  # another route may have spent it during the DNS await
                    return await refuse()
                resp = await route.fetch(max_redirects=0, **kw)
                # ponytail: the driver still buffers one whole response before we can look at it. An oversized
                # one is skipped, not fatal, so it still adds its declared size to the budget below: that is
                # what stops a hostile page making us buffer endless oversized files. Upgrade: httpx streaming guard.
                declared = int(resp.headers.get("content-length") or 0)
                if declared > limit:
                    total += declared
                    return await refuse()
                body = await resp.body()
                total += len(body)
                if len(body) > limit or total > 10 * max_bytes:  # per-job budget, all requests
                    return await refuse()
                loc = resp.headers.get("location")
                if resp.status not in (301, 302, 303, 307, 308) or not loc:
                    # ponytail: page.url stays the original URL after a redirect
                    return await route.fulfill(response=resp)
                url = urljoin(url, loc)
                kw = {"url": url, **({"method": "GET"} if resp.status in (301, 302, 303) else {})}
            await route.abort()  # redirect loop
        except Blocked as e:
            blocked.append(str(e))
            await route.abort("blockedbyclient")
        except PlaywrightError:
            await route.abort()

    # ponytail: browser per job; pool it if launch cost (~0.3s) matters
    async with asyncio.timeout(timeout_s), async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context(accept_downloads=False, reduced_motion="reduce",
                                            service_workers="block",
                                            viewport={"width": 1280, "height": 800})
            await ctx.route("**/*", guard)
            await ctx.route_web_socket("**/*", lambda ws: ws.close())  # never open a real socket
            yield ctx, blocked, skipped
        finally:
            await browser.close()
            # after close, so teardown-time records count; in finally, so exceptional exits too
            if "too_large" in blocked:
                raise ValueError("too_large")


# Titles and headings of bot-check and block pages that answer 200. Body text is not matched: an article may say these.
BLOCK_PHRASES = ("attention required", "you have been blocked", "just a moment", "performing security verification",
                 "verify you are human", "access denied")
BLOCK_SLACK = 20  # a title or heading is a block page only if it is little more than the phrase
HTML_TYPES = ("text/html", "application/xhtml+xml")
LOOK_WAIT_S = 3
# Does anything a person can see sit in the body, open shadow roots included? Frames are not entered: the scanner
# does not enter them either. Also returns the title and first h1 and h2 for the block-page check.
LOOK_JS = r"""(() => {
  const vis = e => !!e && e.checkVisibility({visibilityProperty: true});
  const shown = 'a[href],button,input:not([type=hidden]),select,textarea,img,svg,canvas,video';
  const heads = [document.title, ...['h1', 'h2'].map(t => (document.querySelector(t) || {}).innerText || '')];
  const body = document.body;
  if (!vis(body)) return {content: false, heads};
  const stack = [body];
  while (stack.length) {
    const n = stack.pop();
    for (const c of n.childNodes) {
      if (c.nodeType === 3) {
        if (c.data.trim() && vis(c.parentElement || n.host)) return {content: true, heads};
      } else if (c.nodeType === 1) {
        if (c.matches(shown) && vis(c)) return {content: true, heads};
        stack.push(c);
        if (c.shadowRoot) stack.push(c.shadowRoot);
      }
    }
  }
  return {content: false, heads};
})()"""


def _is_block_page(heads) -> bool:
    return any(p in h and len(h) <= len(p) + BLOCK_SLACK for h in (x.strip().lower() for x in heads) for p in BLOCK_PHRASES)


def _check_response(resp) -> None:
    if not 200 <= resp.status <= 299:
        raise ValueError("not_loaded")
    kind = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind and kind not in HTML_TYPES:
        raise ValueError("not_html")


async def _check_content(page) -> None:
    """Scripts may still be rendering, so look for up to 3 s and judge where the page lands. Refuses as blank only
    when a look at the end answered "empty": a busy or navigating page gives no answer, and the job deadline decides.
    Polls with evaluate, not wait_for_function: a strict page CSP blocks the latter's polling."""
    loop = asyncio.get_running_loop()
    end = loop.time() + LOOK_WAIT_S
    look = None
    while True:
        try:
            look = await asyncio.wait_for(page.evaluate(LOOK_JS), max(end - loop.time(), 0.1))
        except (PlaywrightError, TimeoutError):  # navigating or busy: not an answer
            look = None
        if (look and look["content"]) or loop.time() >= end:
            break
        await asyncio.sleep(0.1)
    if look is None:
        return
    if not look["content"] or _is_block_page(look["heads"]):
        raise ValueError("not_loaded")


@asynccontextmanager
async def open_page(url, *, allow_ips=frozenset(), timeout_s: float = 30, max_bytes: int = 2_000_000,
                    main_max_bytes: int = 5_000_000):
    """Yields (page, html, skipped). skipped is live: fetches can land during the caller's body, so read it after exit.
    Raises ValueError not_loaded for an error status, a blank page or a block page, and not_html for a file."""
    async with _context(timeout_s, allow_ips, max_bytes, main_max_bytes=main_max_bytes) as (ctx, blocked, skipped):
        await asyncio.to_thread(check_url, url, allow_ips)  # DNS, under the deadline
        page = await ctx.new_page()
        try:
            resp = await page.goto(url, timeout=0)  # wall-clock cap is the asyncio.timeout above
        except PlaywrightError as e:
            if "too_large" in blocked:
                raise ValueError("too_large")
            if blocked:
                raise Blocked(blocked[0])
            if "Download is starting" in str(e):
                raise ValueError("not_html")
            raise
        if "too_large" in blocked:
            raise ValueError("too_large")
        if blocked and resp is None:
            raise Blocked(blocked[0])
        _check_response(resp)
        html = (await resp.body()).decode("utf-8", "replace")  # before the wait: a script may navigate away from it
        await _check_content(page)
        yield page, html, skipped


@asynccontextmanager
async def open_html(html, base_url, *, allow_ips=frozenset(), timeout_s: float = 30, max_bytes: int = 2_000_000):
    # Served at base_url (not about:blank) under CSP: page scripts never run, so they cannot
    # detect the rescan and hide violations. A page meta CSP can only tighten this.
    # No frames or workers either (their documents would not carry this CSP), and the main frame
    # never navigates away (meta refresh), so what we scan is exactly `html`.
    # axe still runs: CDP Runtime.evaluate in an isolated world is exempt from page CSP.
    async with _context(timeout_s, allow_ips, max_bytes) as (ctx, _, _):
        page = await ctx.new_page()
        served = False

        async def main_doc(route):
            nonlocal served
            if not route.request.is_navigation_request() or route.request.frame != page.main_frame:
                return await route.fallback()  # subresources go through the context guard
            if served:
                # re-navigation would replace the served document. Not abort(): that commits a
                # chrome-error page. A 204 cancels the navigation and keeps the current document.
                return await route.fulfill(status=204)
            served = True
            await route.fulfill(status=200, body=html, headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Security-Policy": "script-src 'none'; object-src 'none'; base-uri 'none'; "
                                           "frame-src 'none'; child-src 'none'; worker-src 'none'"})

        await page.route("**/*", main_doc)  # page routes run before the context's catch-all guard
        await page.goto(base_url, timeout=0)  # wall-clock cap is _context's asyncio.timeout
        yield page
