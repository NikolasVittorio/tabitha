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
async def _context(timeout_s, allow_ips):
    """Fresh browser+context with the guard installed; yields (context, blocked_list)."""
    blocked: list[str] = []

    async def guard(route):
        url, kw = route.request.url, {}
        try:
            # Chromium follows redirects of routed requests internally, unchecked. So fetch
            # with max_redirects=0 and follow hops here, checking every hop.
            for _ in range(10):
                # getaddrinfo blocks, keep it off the event loop
                await asyncio.to_thread(check_url, url, allow_ips)
                resp = await route.fetch(max_redirects=0, **kw)
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
                                            viewport={"width": 1280, "height": 800})
            await ctx.route("**/*", guard)
            yield ctx, blocked
        finally:
            await browser.close()


@asynccontextmanager
async def open_page(url, *, allow_ips=frozenset(), timeout_s: float = 30, max_bytes: int = 2_000_000):
    check_url(url, allow_ips)
    async with _context(timeout_s, allow_ips) as (ctx, blocked):
        page = await ctx.new_page()
        try:
            resp = await page.goto(url, timeout=0)  # wall-clock cap is the asyncio.timeout above
        except PlaywrightError:
            if blocked:
                raise Blocked(blocked[0])
            raise
        if blocked and resp is None:
            raise Blocked(blocked[0])
        body = await resp.body()
        if len(body) > max_bytes:
            raise ValueError("too_large")
        yield page, body.decode("utf-8", "replace")


@asynccontextmanager
async def open_html(html, base_url, *, allow_ips=frozenset(), timeout_s: float = 30):
    async with _context(timeout_s, allow_ips) as (ctx, _):
        page = await ctx.new_page()
        await page.set_content(f'<base href="{escape(base_url, quote=True)}">{html}')
        yield page
