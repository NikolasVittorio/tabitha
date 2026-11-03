"""Deterministic keyboard walk: Tab through the page and report traps, modal escapes and invisible focus."""
from playwright.async_api import Page

from gate.models import Finding

TESTED = ["2.1.1", "2.1.2", "2.4.3", "2.4.7"]
CAP = 10

# Installs helpers on window: __a11yPath(el) -> stable CSS path, __a11yTargets(root) -> visible tabbables,
# __a11yModal() -> first visible open modal.
_JS = r"""() => {
  window.__a11yPath = el => {
    const parts = [];
    for (; el && el.nodeType === 1; el = el.parentElement) {
      if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
      let i = 1;
      for (let s = el.previousElementSibling; s; s = s.previousElementSibling) if (s.localName === el.localName) i++;
      parts.unshift(el.localName + ':nth-of-type(' + i + ')');
    }
    return parts.join(' > ');
  };
  const shown = el => el.checkVisibility({visibilityProperty: true}) && el.getClientRects().length > 0;
  window.__a11yTargets = root => [...root.querySelectorAll(
      'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')]
    .filter(el => el.tabIndex >= 0 && !el.disabled && !el.closest('[inert]') && shown(el));
  window.__a11yModal = () => [...document.querySelectorAll('[aria-modal="true"],dialog[open]')].find(shown) || null;
}"""

# Real (non-body) focused element, or null.
_ACTIVE = "() => { const a = document.activeElement; return a && a !== document.body ? a : null; }"


def _f(rule, status, wcag, selector, message):
    return Finding(rule_id=rule, source="walker", status=status, impact=None, selector=selector,
                   wcag=[wcag], message=message)


async def _modal_check(page: Page) -> list[Finding]:
    await page.evaluate(_JS)
    sel = await page.evaluate("""() => {
      const m = window.__a11yModal(); if (!m) return null;
      window.__a11yOpener = document.activeElement;
      // ponytail: a modal open on load has no opener; the pre-entry activeElement (usually body) stands in
      const first = window.__a11yTargets(m)[0]; if (first) first.focus();
      window.__a11yM = m; return window.__a11yPath(m);
    }""")
    if sel is None:
        return []
    out = []
    for _ in range(10):
        await page.keyboard.press("Tab")
        if not await page.evaluate("() => window.__a11yM.contains(document.activeElement)"):
            out.append(_f("modal-focus-escape", "fail", "2.4.3", sel, "Tab moves focus out of an open modal dialog."))
            break
    await page.keyboard.press("Escape")
    if await page.evaluate("""() => document.contains(window.__a11yM) && window.__a11yM.checkVisibility()
                              || document.activeElement !== window.__a11yOpener"""):
        out.append(_f("modal-focus-return", "needs_review", "2.4.3", sel,
                      "Escape did not close the dialog and return focus to its opener."))
    await page.reload()
    return out


async def _focus_visible(page: Page, el) -> bool | None:
    """Screenshot the element's box +4px blurred and focused; identical bytes means no visible indicator."""
    await el.evaluate("e => e.scrollIntoView({block: 'center'})")
    box = await el.bounding_box()  # taken while focused, so focus-only content (skip links) is inside the clip
    if not box or box["width"] < 1 or box["height"] < 1:
        return None
    x, y = max(box["x"] - 4, 0), max(box["y"] - 4, 0)
    clip = {"x": x, "y": y, "width": box["x"] + box["width"] + 4 - x, "height": box["y"] + box["height"] + 4 - y}
    await el.evaluate("e => e.blur()")
    before = await page.screenshot(clip=clip, animations="disabled")
    await el.evaluate("e => e.focus({preventScroll: true})")
    after = await page.screenshot(clip=clip, animations="disabled")
    return before != after


async def walk(page: Page, max_presses: int = 50) -> tuple[list[Finding], list[str], list[str]]:
    findings = await _modal_check(page)
    await page.evaluate(_JS)
    history: list[str] = []  # every non-body focus, in press order
    seen: dict[str, object] = {}  # selector -> element handle, first-visit order
    in_modal: dict[str, bool] = {}
    cycle = False
    checks = 0
    for _ in range(max_presses):
        await page.keyboard.press("Tab")
        el = (await page.evaluate_handle(_ACTIVE)).as_element()
        if el is None:  # focus left to body/browser chrome between cycles; not an entry
            continue
        sel = await el.evaluate("e => window.__a11yPath(e)")
        if history and sel == history[0]:
            cycle = True
            break
        history.append(sel)
        if sel in seen:
            continue
        seen[sel] = el
        in_modal[sel] = await el.evaluate("e => !!e.closest('[aria-modal=\"true\"],dialog[open]')")
        if checks < CAP:
            checks += 1
            if await _focus_visible(page, el) is False:
                findings.append(_f("focus-not-visible", "fail", "2.4.7", sel,
                                   "Keyboard focus produces no visible change on this element."))
    tail = history[-10:]
    if not cycle and len(tail) == 10 and len(set(tail)) <= 2 and not any(in_modal[s] for s in tail):
        findings.append(_f("kbd-trap", "fail", "2.1.2", tail[-1], "Tab cannot move focus away from this element."))
    # ponytail: with an open modal only its contents are expected to be reachable
    unvisited = await page.evaluate("""seen => window.__a11yTargets(window.__a11yModal() || document)
                                       .map(window.__a11yPath).filter(s => !seen.includes(s))""", list(seen))
    for sel in unvisited[:CAP]:
        findings.append(_f("kbd-unreachable", "needs_review", "2.1.1", sel, "Tab never reached this element."))
        # A trap hides everything after it, so still check the indicator, focusing the element from script.
        # Chromium keeps :focus-visible for script focus after keyboard input, so the result matches Tab.
        if checks < CAP:
            checks += 1
            el = await page.query_selector(sel)
            await el.evaluate("e => e.focus()")
            if await _focus_visible(page, el) is False:
                findings.append(_f("focus-not-visible", "fail", "2.4.7", sel,
                                   "Focus produces no visible change on this element (focused from script; "
                                   "Tab never reached it)."))
    return findings, list(seen), list(TESTED)
