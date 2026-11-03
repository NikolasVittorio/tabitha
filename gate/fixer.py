from urllib.parse import urlparse

from bs4 import BeautifulSoup

from gate.allowlist import parse, patch_violations, unparseable_style
from gate.contrast import fix_fg
from gate.models import Finding, Fix

LABEL_RULES = {"button-name", "link-name", "label", "select-name"}


def _set_color(el, color: str) -> None:
    decl = [p.strip() for p in el.get("style", "").split(";") if p.strip()]
    decl = [p for p in decl if p.split(":")[0].strip().lower() != "color"]
    el["style"] = ";".join(decl + [f"color:{color}"])


def _apply(soup: BeautifulSoup, f: Finding) -> tuple[str, str]:
    """Mutate soup for one finding; return (outcome, note)."""
    r = f.rule_id
    if r == "image-alt":
        return "needs_author", "alt text needs a human description"
    if r not in LABEL_RULES | {"html-has-lang", "document-title", "color-contrast", "duplicate-id"}:
        return "not_fixed", "no deterministic fix for this rule"
    el = soup.select_one(f.selector)
    if el is None:
        return "not_fixed", "selector matched nothing"
    if r == "html-has-lang":
        el["lang"] = "en"
        return "fixed", 'set lang="en"; verify the page language'
    if r == "document-title":
        head, h1 = soup.find("head"), soup.find("h1")
        if head is None:  # ponytail: adding <head> would break the allowlist's tag-sequence rule
            return "not_fixed", "no <head> to hold a title"
        t = (h1.get_text(" ", strip=True) if h1 else "") or urlparse(f.data.get("url", "")).hostname or "Untitled page"
        tag = soup.new_tag("title")
        tag.string = t
        head.append(tag)
        return "fixed", "title inserted; verify wording"
    if r == "color-contrast":
        if unparseable_style(el.get("style")):
            return "not_fixed", "unparseable inline style"
        d = f.data
        try:
            target = float(str(d["expectedContrastRatio"]).split(":")[0])
            _set_color(el, fix_fg(d["fgColor"], d["bgColor"], target))
        except (KeyError, ValueError):
            return "not_fixed", "missing or unparseable contrast data"
        return "fixed", "foreground colour adjusted"
    if r == "duplicate-id":
        taken = {e["id"] for e in soup.find_all(id=True)}
        n = 2
        while f"{el.get('id', '')}-{n}" in taken:
            n += 1
        el["id"] = f"{el.get('id', '')}-{n}"
        return "fixed", "id renamed; update references"
    name = next((str(el.get(k)).strip() for k in ("placeholder", "title", "name") if str(el.get(k) or "").strip()), "")
    if not name:
        prev = el.find_previous(string=lambda s: s.parent.name not in ("script", "style", "title") and s.strip())
        name = prev.strip() if prev else ""
    if not name:
        return "needs_author", "no label source found"
    el["aria-label"] = name
    return "fixed", "aria-label set; verify wording"


def fix(html: str, findings: list[Finding], rules: set[str] | None = None) -> tuple[str, list[Fix]]:
    todo = [f for f in findings if rules is None or f.rule_id in rules]
    try:
        soup = parse(html)
    except ValueError as e:  # duplicate attributes: serialising would change what browsers see
        return html, [Fix(rule_id=f.rule_id, selector=f.selector, outcome="not_fixed", note=str(e)) for f in todo]
    fixes = []
    for f in todo:
        before = str(soup)
        outcome, note = _apply(soup, f)
        v = patch_violations(before, str(soup))
        if v:  # revert this rule's change
            soup, outcome, note = parse(before), "not_fixed", "; ".join(v)
        fixes.append(Fix(rule_id=f.rule_id, selector=f.selector, outcome=outcome, note=note))
    if not any(x.outcome == "fixed" for x in fixes):
        return html, fixes  # nothing applied: hand back the original bytes, not a re-serialisation
    return str(soup), fixes
