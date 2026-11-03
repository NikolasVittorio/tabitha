"""SSRF-guarded Playwright openers. The only path that loads untrusted pages."""
import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager
from html import escape
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError, async_playwright


class Blocked(Exception):
    pass


class _TooLarge(Exception):
    pass


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
async def _context(timeout_s, allow_ips, max_bytes):
    """Fresh browser+context with the guard installed; yields (context, blocked_list)."""
    blocked: list[str] = []
    total = 0

    async def guard(route):
        nonlocal total
        url, kw = route.request.url, {}
        try:
            # Chromium follows redirects of routed requests internally, unchecked. So fetch
            # with max_redirects=0 and follow hops here, checking every hop.
            for _ in range(10):
                # getaddrinfo blocks, keep it off the event loop
                await asyncio.to_thread(check_url, url, allow_ips)
                resp = await route.fetch(max_redirects=0, **kw)
                # ponytail: the driver still buffers one whole response before we can look at it;
                # the deadline plus the Fly memory limit bound it. Upgrade: httpx streaming guard.
                if int(resp.headers.get("content-length") or 0) > max_bytes:
                    raise _TooLarge
                body = await resp.body()
                total += len(body)
                if len(body) > max_bytes or total > 10 * max_bytes:  # per-job budget, all requests
                    raise _TooLarge
                loc = resp.headers.get("location")
                if resp.status not in (301, 302, 303, 307, 308) or not loc:
                    # ponytail: page.url stays the original URL after a redirect
                    return await route.fulfill(response=resp)
                url = urljoin(url, loc)
                kw = {"url": url, **({"method": "GET"} if resp.status in (301, 302, 303) else {})}
            await route.abort()  # redirect loop
        except _TooLarge:
            blocked.append("too_large")
            await route.abort("blockedbyclient")
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
            yield ctx, blocked
        finally:
            await browser.close()


@asynccontextmanager
async def open_page(url, *, allow_ips=frozenset(), timeout_s: float = 30, max_bytes: int = 2_000_000):
    async with _context(timeout_s, allow_ips, max_bytes) as (ctx, blocked):
        await asyncio.to_thread(check_url, url, allow_ips)  # DNS, under the deadline
        page = await ctx.new_page()
        try:
            resp = await page.goto(url, timeout=0)  # wall-clock cap is the asyncio.timeout above
        except PlaywrightError:
            if "too_large" in blocked:
                raise ValueError("too_large")
            if blocked:
                raise Blocked(blocked[0])
            raise
        if "too_large" in blocked:
            raise ValueError("too_large")
        if blocked and resp is None:
            raise Blocked(blocked[0])
        yield page, (await resp.body()).decode("utf-8", "replace")


@asynccontextmanager
async def open_html(html, base_url, *, allow_ips=frozenset(), timeout_s: float = 30):
    async with _context(timeout_s, allow_ips, 2_000_000) as (ctx, _):
        page = await ctx.new_page()
        await page.set_content(f'<base href="{escape(base_url, quote=True)}">{html}')
        yield page
