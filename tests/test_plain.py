import re
from pathlib import Path

from playwright.async_api import async_playwright

from gate.plain import ERRORS, GENERIC_ERROR, PLAIN, UNMAPPED_TODO
from gate.scanner import AXE_SRC

BANNED = r"\b(pass|passed|compliant|compliance|certified|certify|conformant|conformance|agent-ready)\b"
REQUIRED = """image-alt input-image-alt area-alt svg-img-alt role-img-alt object-alt link-name button-name label select-name
input-button-name color-contrast html-has-lang html-lang-valid valid-lang document-title frame-title aria-required-attr
aria-valid-attr aria-valid-attr-value aria-roles aria-allowed-attr aria-hidden-focus aria-required-children
aria-required-parent list listitem definition-list dlitem duplicate-id-aria meta-viewport meta-refresh target-size
td-headers-attr th-has-data-cells autocomplete-valid form-field-multiple-labels link-in-text-block nested-interactive
scrollable-region-focusable video-caption audio-caption focus-not-visible kbd-trap modal-focus-escape""".split()


async def test_every_row_names_a_rule_axe_or_the_walker_can_raise():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("<p>x</p>")
        await page.evaluate(AXE_SRC)
        axe_ids = set(await page.evaluate("axe.getRules().map(r => r.ruleId)"))
        await browser.close()
    walker = (Path(__file__).resolve().parent.parent / "gate" / "walker.py").read_text("utf-8")
    assert set(PLAIN) - axe_ids - set(re.findall(r'_f\("([a-z-]+)"', walker)) == set()


def test_the_rules_testers_hit_have_plain_wording():
    assert set(REQUIRED) - set(PLAIN) == set()
    assert "skip-link-broken" in PLAIN


def test_each_row_is_one_short_sentence():
    for rule, (problem, todo) in PLAIN.items():
        assert "." not in problem, rule
        assert todo.endswith(".") and ". " not in todo and len(todo) <= 220, rule


def test_plain_wording_avoids_the_words_the_product_never_says():
    texts = [t for row in PLAIN.values() for t in row] + list(ERRORS.values()) + [GENERIC_ERROR, UNMAPPED_TODO]
    assert [t for t in texts if re.search(BANNED, t, re.I)] == []
