import time
import pytest
from bs4 import BeautifulSoup
from gate.browser import open_page
from gate.walker import walk
LOCAL = frozenset({"127.0.0.1"})
async def ids(http_server, name):
    async with open_page(f"{http_server}/{name}", allow_ips=LOCAL) as (page, _):
        f, path, tested = await walk(page)
    return {x.rule_id: x.status for x in f}, path, tested
async def test_trap_detected(http_server):
    r, _, _ = await ids(http_server, "trap.html")
    assert r.get("kbd-trap") == "fail"
    # the link behind the trap has a default ring: script focus must not report it invisible
    assert "focus-not-visible" not in r
async def test_focus_not_visible(http_server):
    r, _, _ = await ids(http_server, "broken.html")
    assert r.get("focus-not-visible") == "fail"
async def test_modal_escape(http_server):
    r, _, _ = await ids(http_server, "modal.html")
    assert r.get("modal-focus-escape") == "fail"
async def test_clean_has_no_fails(http_server):
    r, path, tested = await ids(http_server, "clean.html")
    assert "fail" not in r.values() and len(path) >= 3 and "2.1.2" in tested
    assert "focus-obscured" not in r
async def test_forged_focus_is_unverifiable(http_server):
    r, _, _ = await ids(http_server, "hostile.html")
    assert r.get("walk-unverifiable") == "needs_review"
@pytest.mark.parametrize("name", ["trap-first.html", "loop.html", "loop-hidden-override.html"])
async def test_trap_on_first_element_and_two_element_loop(http_server, name):
    r, _, _ = await ids(http_server, name)
    assert r.get("kbd-trap") == "fail"
async def test_offset_ring_is_not_a_fail(http_server):
    r, _, _ = await ids(http_server, "ring.html")
    assert "fail" not in r.values() and "focus-visibility-unverified" not in r
async def test_changing_pixels_need_review(http_server):
    r, _, _ = await ids(http_server, "animated.html")
    assert r.get("focus-visibility-unverified") == "needs_review" and "fail" not in r.values()
@pytest.mark.parametrize("name", ["radios.html", "radios-link.html", "one-link.html", "skip-link.html"])
async def test_no_false_trap_or_unreachable(http_server, name):
    r, path, _ = await ids(http_server, name)
    assert path and "kbd-trap" not in r and "kbd-unreachable" not in r
    assert "focus-obscured" not in r
async def test_selectors_resolve_in_page_html(http_server):
    # the fixer targets these selectors with soupsieve
    async with open_page(f"{http_server}/broken.html", allow_ips=LOCAL) as (page, html):
        f, path, _ = await walk(page)
    soup = BeautifulSoup(html, "html.parser")
    assert path and all(soup.select_one(s) is not None for s in path + [x.selector for x in f])
async def test_focus_checked_beyond_ten_stops(http_server):
    async with open_page(f"{http_server}/many-plain.html", allow_ips=LOCAL) as (page, _):
        f, _, _ = await walk(page)
    assert sum(x.rule_id == "focus-not-visible" for x in f) == 15
async def test_focus_budget_reports_partial(http_server, monkeypatch):
    monkeypatch.setattr("gate.walker.FOCUS_BUDGET_S", 0.0)
    r, _, _ = await ids(http_server, "many-plain.html")
    assert r.get("focus-visibility-partial") == "needs_review" and "focus-not-visible" not in r
async def test_walk_fits_deadline(http_server):
    t = time.monotonic()
    await ids(http_server, "many-plain.html")
    assert time.monotonic() - t < 25  # inside the 30 s page context
async def test_focus_obscured_by_fixed_banner(http_server):
    r, _, tested = await ids(http_server, "cookie-banner.html")
    assert r.get("focus-obscured") == "needs_review" and "2.4.11" in tested
async def test_partly_covered_focus_is_not_obscured(http_server):
    r, _, _ = await ids(http_server, "banner-partial.html")
    assert "focus-obscured" not in r
