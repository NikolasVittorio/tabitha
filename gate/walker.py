"""Deterministic keyboard walk: Tab through the page and report traps, modal escapes and invisible focus."""
from playwright.async_api import Page

from gate.models import Finding

TESTED = ["2.1.1", "2.1.2", "2.4.3", "2.4.7"]
CAP = 10
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
_TARGETS = r"""const targets = root => [...root.querySelectorAll(
    'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')]
  .filter(el => el.tabIndex >= 0 && !el.disabled && !el.closest('[inert]') && shown(el));"""
_MODAL = """const modal = () => [...document.querySelectorAll('[aria-modal="true"],dialog[open]')].find(shown) || null;"""
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
    try:
        findings += await _modal_check(page)
        history: list[str] = []  # every non-body focus, in press order
        cycle = False
        checks = 0
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
            if checks < CAP:
                checks += 1
                await _check_focus(page, el, sel, findings)
        unvisited = await _unvisited(page, seen)
        tail = history[-10:]
        if (not cycle and len(tail) == 10 and len(set(tail)) <= 2 and not any(seen[s] for s in tail)
                and (len(seen) >= 2 or unvisited)):
            findings.append(_f("kbd-trap", "fail", "2.1.2", tail[-1], "Tab cannot move focus away from this element."))
        for sel in unvisited[:CAP]:
            findings.append(_f("kbd-unreachable", "needs_review", "2.1.1", sel, "Tab never reached this element."))
            # A trap hides everything after it, so still check the indicator, focusing the element from script.
            # Chromium keeps :focus-visible for script focus after keyboard input, so the result matches Tab.
            if checks < CAP:
                checks += 1
                el = await page.query_selector(sel)
                await el.evaluate("e => e.focus()")
                await _check_focus(page, el, sel, findings, " (focused from script; Tab never reached it)")
    except _Unverifiable:
        findings.append(_f("walk-unverifiable", "needs_review", "2.1.1", "html",
                           "The page reported focus inconsistently, so the keyboard walk was stopped "
                           "and its results cannot be relied on."))
    return findings, list(seen), list(TESTED)
