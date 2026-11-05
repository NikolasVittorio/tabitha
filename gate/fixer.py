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


ADJACENT_MAX = 40


def _adjacent_text(el) -> str:
    """The text right before a button or link in the same parent, like <span>Buy now</span><button>. Anything further
    away is a guess, and so is any neighbour of a form field: a radio's own label comes after it, so the text before
    the Mrs radio says Mr."""
    if el.name not in ("button", "a"):
        return ""
    for s in el.previous_siblings:
        t = (s if isinstance(s, str) else s.get_text(" ", strip=True)).strip()
        if t:
            return t if len(t) <= ADJACENT_MAX else ""
    return ""


def _apply(soup: BeautifulSoup, f: Finding) -> tuple:
    """Mutate soup for one finding; return (outcome, note), plus the changes made when fixed."""
    r = f.rule_id
    if r == "image-alt":
        return "needs_author", "alt text needs a human description"
    if r not in LABEL_RULES | {"html-has-lang", "document-title", "color-contrast", "duplicate-id"}:
        return "not_fixed", "no deterministic fix for this rule"
    if f.data.get("nested"):
        return "not_fixed", "target is inside a frame or shadow root"
    try:
        el = soup.select_one(f.selector)
    except Exception:  # soupsieve SelectorSyntaxError and friends
        return "not_fixed", "invalid selector"
    if el is None:
        return "not_fixed", "selector matched nothing"
    if r == "html-has-lang":
        el["lang"] = "en"
        return "fixed", 'set lang="en"; verify the page language', {"lang": "en"}
    if r == "document-title":
        head, h1 = soup.find("head"), soup.find("h1")
        if head is None:  # ponytail: adding <head> would break the allowlist's tag-sequence rule
            return "not_fixed", "no <head> to hold a title"
        t = (h1.get_text(" ", strip=True) if h1 else "") or urlparse(f.data.get("url", "")).hostname or "Untitled page"
        tag = soup.new_tag("title")
        tag.string = t
        head.append(tag)
        return "fixed", "title inserted; verify wording", {"<title>": t}
    if r == "color-contrast":
        if unparseable_style(el.get("style")):
            return "not_fixed", "unparseable inline style"
        d = f.data
        try:
            target = float(str(d["expectedContrastRatio"]).split(":")[0])
            color = fix_fg(d["fgColor"], d["bgColor"], target)
            _set_color(el, color)
        except (KeyError, ValueError):
            return "not_fixed", "missing or unparseable contrast data"
        return "fixed", "foreground colour adjusted", {"color": color}
    if r == "duplicate-id":
        taken = {e["id"] for e in soup.find_all(id=True)}
        n = 2
        while f"{el.get('id', '')}-{n}" in taken:
            n += 1
        el["id"] = f"{el.get('id', '')}-{n}"
        return "fixed", "id renamed; update references", {"id": el["id"]}
    name = next((str(el.get(k)).strip() for k in ("placeholder", "title") if str(el.get(k) or "").strip()), "") or _adjacent_text(el)
    if not name:
        href = str(el.get("href") or "")
        return "needs_author", f"needs a name that says where {href} goes" if href else "needs a name that says what this control does"
    el["aria-label"] = name
    return "fixed", "aria-label set; verify wording", {"aria-label": name}


def fix(html: str, findings: list[Finding], rules: set[str] | None = None) -> tuple[str, list[Fix]]:
    todo = [f for f in findings if rules is None or f.rule_id in rules]
    try:
        soup = parse(html)
    except ValueError as e:  # duplicate attributes: serialising would change what browsers see
        return html, [Fix(rule_id=f.rule_id, selector=f.selector, outcome="not_fixed", note=str(e)) for f in todo]
    fixes = []
    for f in todo:
        before = str(soup)
        outcome, note, *made = _apply(soup, f)
        changes = made[0] if made else {}
        v = patch_violations(before, str(soup))
        if v:  # revert this rule's change
            soup, outcome, note, changes = parse(before), "not_fixed", "; ".join(v), {}
        fixes.append(Fix(rule_id=f.rule_id, selector=f.selector, outcome=outcome, note=note, changes=changes))
    if not any(x.outcome == "fixed" for x in fixes):
        return html, fixes  # nothing applied: hand back the original bytes, not a re-serialisation
    return str(soup), fixes
