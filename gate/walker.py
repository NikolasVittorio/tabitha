"""Deterministic keyboard walk: Tab through the page and report traps, modal escapes, dead skip links and invisible focus."""
import time

from playwright.async_api import Page

from gate.models import Finding

TESTED = ["2.1.1", "2.1.2", "2.4.3", "2.4.7", "2.4.11"]
CAP = 10  # most kbd-unreachable findings listed
# ponytail: walk-wide wall clock, read between stops, so one slow check can overshoot it and time spent before
# walk (page load) is not counted; upgrade: derive it from the time left on open_page's deadline
FOCUS_BUDGET_S = 10.0
MARGIN = 24  # px around the element box; a ring drawn further out is still caught by the style signature

# JS snippets inlined into each evaluate body. Nothing is installed on window, so the page has no
# walker globals to overwrite. evaluate still runs in the page's main world, so the page can lie to it;
# the :focus vs activeElement cross-check in _focused is the defence against a forged walk.
_PATH = r"""const path = el => {
  const parts = [];
  for (; el && el.nodeType === 1; el = el.parentElement) {
    if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
    let i = 1;
    for (let s = el.previousElementSibling; s; s = s.previousElementSibling) if (s.localName === el.localName) i++;
    parts.unshift(el.localName + ':nth-of-type(' + i + ')');
  }
  return parts.join(' > ');
};"""
_SHOWN = "const shown = el => el.checkVisibility({visibilityProperty: true}) && el.getClientRects().length > 0;"
# Expected Tab stops. A named radio group (same name, same form) is ONE stop: the checked radio, else the first.
_TARGETS = r"""const targets = root => {
  const all = [...root.querySelectorAll('a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')]
    .filter(el => el.tabIndex >= 0 && !el.matches(':disabled') && !el.closest('[inert]') && shown(el));  // CSS can override [hidden]; shown() judges rendering
  const radio = el => el.localName === 'input' && el.type === 'radio' && el.name;
  return all.filter(el => {
    if (!radio(el)) return true;
    const g = all.filter(r => radio(r) && r.name === el.name && r.form === el.form);
    return el === (g.find(r => r.checked) || g[0]);
  });
};"""
_MODAL = """const modal = () => [...document.querySelectorAll('[aria-modal="true"],dialog[open]')].find(shown) || null;"""
# ponytail: English wording only, so a skip link in another language goes unchecked; add words as pages need them
_SKIP = r"""const skip = () => modal() ? null : [...document.querySelectorAll('a[href^="#"]')]
  .find(a => shown(a) && /\bskip\b|\bjump to\b/i.test(a.getAttribute('aria-label') || a.textContent)) || null;"""
_TARGET = r"""const target = a => { let id = a.hash.slice(1); try { id = decodeURIComponent(id); } catch {}
  const t = id && (document.getElementById(id) || document.getElementsByName(id)[0]); return t && shown(t) ? t : null; };"""
# outline:none leaves the UA focus-visible outline-offset/width in place; they draw nothing, so drop them
_SIG = r"""const sig = e => { const s = getComputedStyle(e);
  const o = s.outlineStyle === 'none' ? ['outline-style'] : ['outline-style', 'outline-width', 'outline-color', 'outline-offset'];
  return [...o, 'box-shadow', 'border-color', 'background-color', 'text-decoration']
    .map(p => s.getPropertyValue(p)).join('|'); };"""


class _Unverifiable(Exception):
    pass


def _f(rule, status, wcag, selector, message):
    return Finding(rule_id=rule, source="walker", status=status, impact=None, selector=selector,
                   wcag=[wcag], message=message)


async def _focused(page: Page):
    """The focused element (None for body/nothing), read two independent ways; disagreement means forgery."""
    loc = page.locator(":focus")  # browser-native :focus match, immune to activeElement/prototype overrides
    n = await loc.count()
    if n == 0:
        if await page.evaluate("() => [null, document.body, document.documentElement].includes(document.activeElement)"):
            return None
        raise _Unverifiable
    # ponytail: an open shadow root also matches its host (count 2) and lands here as unverifiable;
    # resolve to the innermost match if web-component pages start showing up as walk-unverifiable
    if n != 1 or not await loc.evaluate("e => e === document.activeElement"):
        raise _Unverifiable
    return await loc.element_handle()


async def _sel(el) -> str:
    return await el.evaluate("e => {" + _PATH + "return path(e); }")


async def _unvisited(page: Page, seen) -> list[str]:
    # ponytail: with an open modal only its contents are expected to be reachable
    return await page.evaluate("seen => {" + _SHOWN + _TARGETS + _MODAL + _PATH +
                               "return targets(modal() || document).map(path).filter(s => !seen.includes(s)); }",
                               list(seen))


async def _modal_check(page: Page) -> list[Finding]:
    m = (await page.evaluate_handle("() => {" + _SHOWN + _MODAL + "return modal(); }")).as_element()
    if m is None:
        return []
    sel = await _sel(m)
    # ponytail: a modal open on load has no opener; whatever held focus before (usually body) stands in
    opener = await _focused(page)
    await m.evaluate("m => {" + _SHOWN + _TARGETS + "const t = targets(m)[0]; if (t) t.focus(); }")
    out = []
    for _ in range(10):
        await page.keyboard.press("Tab")
        el = await _focused(page)
        if el is None or not await m.evaluate("(m, e) => m.contains(e)", el):
            out.append(_f("modal-focus-escape", "fail", "2.4.3", sel, "Tab moves focus out of an open modal dialog."))
            break
    await page.keyboard.press("Escape")
    after = await _focused(page)
    returned = (after is None and opener is None) or (
        after is not None and opener is not None and await page.evaluate("([a, b]) => a === b", [after, opener]))
    if await m.evaluate("m => m.isConnected && m.checkVisibility()") or not returned:
        out.append(_f("modal-focus-return", "needs_review", "2.4.3", sel,
                      "Escape did not close the dialog and return focus to its opener."))
    await page.reload()
    return out


async def _skip_check(page: Page) -> list[Finding]:
    link = (await page.evaluate_handle("() => {" + _SHOWN + _MODAL + _SKIP + "return skip(); }")).as_element()
    if link is None:
        return []
    sel = await _sel(link)
    dead = _f("skip-link-broken", "fail", "2.4.1", sel, "This skip link does not move the keyboard past the menu.")
    target = (await link.evaluate_handle("a => {" + _SHOWN + _TARGET + "return target(a); }")).as_element()
    if target is None:
        return [dead]
    url = page.url
    await link.evaluate("a => a.focus()")
    await page.keyboard.press("Enter")
    out = []
    el = await _focused(page)
    if el is None or not await target.evaluate("(t, e) => t.contains(e)", el):
        await page.keyboard.press("Tab")
        el = await _focused(page)
        # Chromium moves its Tab starting point even when focus stays put, so the next Tab shows if the skip really worked.
        # No element at all means nothing focusable follows the target, which is not the link's fault.
        ahead = el is None or await target.evaluate("(t, e) => t.contains(e) || !!(t.compareDocumentPosition(e) & 4)", el)
        out.append(_f("skip-link-focus", "needs_review", "2.4.1", sel,
                      "The skip link scrolls the page, but keyboard focus does not move to its target.") if ahead else dead)
    # the fragment must go first: reloading with it would start the walk at the target and report the menu as unreachable
    # ponytail: a script that sends the skip link to another origin makes replaceState throw, like other hostile-page paths
    await page.evaluate("u => history.replaceState(null, '', u)", url)
    await page.reload()
    return out


async def _obscured(el) -> bool:
    """True when the element is entirely under other content or outside the viewport: its box clipped to the viewport
    is empty, or no sample point (centre and corners inset 2px, of that clipped box) hits it or a relative."""
    # ponytail: elementFromPoint skips pointer-events:none overlays (a veil over the element goes unseen), returns the
    # ancestor for an ancestor ::before/::after veil (so that is missed too), and runs in the page's main world, so a
    # page can fake it; hence needs_review only. upgrade: isolated-world hit test
    return await el.evaluate("""e => {
      const b = e.getBoundingClientRect();
      const l = Math.max(b.left, 0), t = Math.max(b.top, 0), r = Math.min(b.right, innerWidth), d = Math.min(b.bottom, innerHeight);
      if (r < l || d < t) return true;
      return [[(l + r) / 2, (t + d) / 2], [l + 2, t + 2], [r - 2, t + 2], [l + 2, d - 2], [r - 2, d - 2]]
        .filter(([x, y]) => x >= 0 && y >= 0 && x < innerWidth && y < innerHeight)
        .every(([x, y]) => { const h = document.elementFromPoint(x, y); return !h || !(e.contains(h) || h.contains(e)); });
    }""")


async def _focus_visible(page: Page, el) -> str | None:
    """'visible', 'invisible' or 'unverified' from blurred vs focused shots of the box + MARGIN; None if no box."""
    await el.evaluate("e => e.scrollIntoView({block: 'center'})")
    box = await el.bounding_box()  # taken while focused, so focus-only content (skip links) is inside the clip
    vw = page.viewport_size or {"width": 1280, "height": 800}
    if not box:
        return None
    x0, y0 = max(box["x"] - MARGIN, 0), max(box["y"] - MARGIN, 0)
    x1 = min(box["x"] + box["width"] + MARGIN, vw["width"])
    y1 = min(box["y"] + box["height"] + MARGIN, vw["height"])
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    clip = {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}
    before_sig = await el.evaluate("e => {" + _SIG + "e.blur(); return sig(e); }")
    before = await page.screenshot(clip=clip, animations="disabled")
    if before != await page.screenshot(clip=clip, animations="disabled"):
        return "unverified"  # region changes on its own; a pixel diff would prove nothing
    after_sig = await el.evaluate("e => {" + _SIG + "e.focus({preventScroll: true}); return sig(e); }")
    if before != await page.screenshot(clip=clip, animations="disabled"):
        return "visible"
    return "invisible" if before_sig == after_sig else "unverified"


async def _check_focus(page: Page, el, sel, findings, note=""):
    r = await _focus_visible(page, el)
    if r == "invisible":
        findings.append(_f("focus-not-visible", "fail", "2.4.7", sel,
                           "Keyboard focus produces no visible change on this element" + note + "."))
    elif r == "unverified":
        findings.append(_f("focus-visibility-unverified", "needs_review", "2.4.7", sel,
                           "Focus visibility could not be confirmed automatically (region changes on its own, "
                           "or styles change with no pixel difference)" + note + "."))


async def walk(page: Page, max_presses: int = 50) -> tuple[list[Finding], list[str], list[str]]:
    findings: list[Finding] = []
    seen: dict[str, bool] = {}  # selector -> inside a modal, in first-visit order
    start = time.monotonic()  # the modal check and its reload count against the focus budget
    try:
        findings += await _modal_check(page)
        findings += await _skip_check(page)
        history: list[str] = []  # every non-body focus, in press order
        cycle = False
        checked = skipped = 0  # focus stops whose indicator was / was not checked before the budget ran out
        for _ in range(max_presses):
            await page.keyboard.press("Tab")
            el = await _focused(page)
            if el is None:  # focus left to body/browser chrome between cycles; not an entry
                continue
            sel = await _sel(el)
            # a lone repeat of element 1 is a trap, not a cycle: require 2+ elements and nothing left to reach
            if history and sel == history[0] and len(seen) >= 2 and not await _unvisited(page, seen):
                cycle = True
                break
            history.append(sel)
            if sel in seen:
                continue
            seen[sel] = await el.evaluate("e => !!e.closest('[aria-modal=\"true\"],dialog[open]')")
            if await _obscured(el):  # before _check_focus, which scrolls the element to the centre
                findings.append(_f("focus-obscured", "needs_review", "2.4.11", sel,
                                   "While it has keyboard focus, this element cannot be seen: it is entirely covered by "
                                   "other content or outside the visible page."))
            if time.monotonic() - start < FOCUS_BUDGET_S:
                checked += 1
                await _check_focus(page, el, sel, findings)
            else:
                skipped += 1
        unvisited = await _unvisited(page, seen)
        tail = history[-10:]
        if (not cycle and len(tail) == 10 and len(set(tail)) <= 2 and not any(seen[s] for s in tail)
                and (len(seen) >= 2 or unvisited)):
            findings.append(_f("kbd-trap", "fail", "2.1.2", tail[-1], "Tab cannot move focus away from this element."))
        for sel in unvisited[:CAP]:
            findings.append(_f("kbd-unreachable", "needs_review", "2.1.1", sel, "Tab never reached this element."))
            # A trap hides everything after it, so still check the indicator, focusing the element from script.
            # Chromium keeps :focus-visible for script focus after keyboard input, so the result matches Tab.
            if time.monotonic() - start < FOCUS_BUDGET_S:
                checked += 1
                el = await page.query_selector(sel)
                await el.evaluate("e => e.focus()")
                await _check_focus(page, el, sel, findings, " (focused from script; Tab never reached it)")
            else:
                skipped += 1
        if skipped:
            findings.append(_f("focus-visibility-partial", "needs_review", "2.4.7", "html",
                               f"Focus visibility was checked on {checked} of {checked + skipped} focus stops "
                               "before the time limit; check the rest by hand."))
    except _Unverifiable:
        findings.append(_f("walk-unverifiable", "needs_review", "2.1.1", "html",
                           "The page reported focus inconsistently, so the keyboard walk was stopped "
                           "and its results cannot be relied on."))
    return findings, list(seen), list(TESTED)
