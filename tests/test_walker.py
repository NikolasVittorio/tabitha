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
async def test_forged_focus_is_unverifiable(http_server):
    r, _, _ = await ids(http_server, "hostile.html")
    assert r.get("walk-unverifiable") == "needs_review"
@pytest.mark.parametrize("name", ["trap-first.html", "loop.html"])
async def test_trap_on_first_element_and_two_element_loop(http_server, name):
    r, _, _ = await ids(http_server, name)
    assert r.get("kbd-trap") == "fail"
async def test_offset_ring_is_not_a_fail(http_server):
    r, _, _ = await ids(http_server, "ring.html")
    assert "fail" not in r.values() and "focus-visibility-unverified" not in r
async def test_changing_pixels_need_review(http_server):
    r, _, _ = await ids(http_server, "animated.html")
    assert r.get("focus-visibility-unverified") == "needs_review" and "fail" not in r.values()
async def test_selectors_resolve_in_page_html(http_server):
    # the fixer targets these selectors with soupsieve
    async with open_page(f"{http_server}/broken.html", allow_ips=LOCAL) as (page, html):
        f, path, _ = await walk(page)
    soup = BeautifulSoup(html, "html.parser")
    assert path and all(soup.select_one(s) is not None for s in path + [x.selector for x in f])
