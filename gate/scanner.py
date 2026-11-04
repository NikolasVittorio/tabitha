import json
from pathlib import Path

from playwright.async_api import Page

from gate.models import Finding
from gate.wcag import from_axe_tags

AXE_SRC = (Path(__file__).parent / "vendor" / "axe.min.js").read_text("utf-8")
TREE_CAP = 20_000
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


async def aria_tree(page: Page) -> str:
    try:
        return (await page.locator("body").aria_snapshot(timeout=5000))[:TREE_CAP]  # 5s: must not eat the context's 30s deadline
    except Exception:  # ponytail: the tree is a nicety, never let it fail the scan
        return ""


# Elements grouped by (link|button, accessible name); only groups of 2+ leave the page, with the first element's selector.
DUPES_JS = r"""(() => {
  axe.setup(document);  // axe.run tore its tree down; accessibleText and getSelector need one
  try {
    const g = new Map();
    for (const e of document.querySelectorAll('a[href],button,[role=button],input[type=submit],input[type=button]')) {
      if (!e.checkVisibility({visibilityProperty: true}) || !e.getClientRects().length) continue;
      const n = axe.commons.text.accessibleText(e).replace(/\s+/g, ' ').trim().toLowerCase();
      if (!n) continue;
      const link = e.tagName === 'A' && e.getAttribute('role') !== 'button', k = (link ? 'l' : 'b') + n;
      if (!g.has(k)) g.set(k, {link, e, hrefs: []});
      g.get(k).hrefs.push(link ? String(e.href).split('#')[0] : '');
    }
    return JSON.stringify([...g.values()].filter(x => x.hrefs.length > 1)
      .map(x => ({link: x.link, sel: axe.utils.getSelector(x.e), hrefs: x.hrefs})));
  } finally { axe.teardown(); }
})()"""
DUPES = 10


async def _dupes(cdp, ctx_id) -> list[Finding]:
    # ponytail: light DOM only, and "different purpose" means a different href once the #fragment is dropped.
    # Upgrade: pierce shadow roots; compare accessible descriptions or surrounding headings too.
    try:
        out = await cdp.send("Runtime.evaluate", {
            "expression": DUPES_JS, "contextId": ctx_id, "returnByValue": True, "timeout": 5000})  # CDP stops a stalled script
        groups = json.loads(out["result"]["value"])
    except Exception:  # ponytail: this check is extra, never let it fail the scan
        return []
    found = []
    for g in groups:
        n, k = len(g["hrefs"]), len(set(g["hrefs"]))
        if g["link"] and k > 1:
            found.append(Finding(rule_id="duplicate-link-name", source="gate", status="needs_review", impact=None,
                                 selector=g["sel"], wcag=["2.4.4"], data={"count": n},
                                 message=f"{n} links share this name but go to {k} different pages."))
        elif not g["link"]:
            found.append(Finding(rule_id="duplicate-button-name", source="gate", status="needs_review", impact=None,
                                 selector=g["sel"], wcag=["2.4.6"], data={"count": n},
                                 message=f"{n} buttons share this name; check that each one says what it does."))
    return found[:DUPES]


async def scan(page: Page) -> tuple[list[Finding], list[str]]:
    # axe runs in a CDP isolated world: page scripts cannot see or reconfigure it, and CSP
    # does not apply to Runtime.evaluate. ponytail: child frames are not provisioned; axe's
    # frame-tested rule surfaces each as needs_review. Upgrade: one isolated world per frame.
    cdp = await page.context.new_cdp_session(page)
    try:
        fid = (await cdp.send("Page.getFrameTree"))["frameTree"]["frame"]["id"]
        ctx_id = (await cdp.send("Page.createIsolatedWorld", {
            "frameId": fid, "worldName": "a11y-gate", "grantUniveralAccess": False}))["executionContextId"]
        opts = json.dumps({"runOnly": {"type": "tag", "values": TAGS},
                           "rules": {"frame-tested": {"enabled": True}}})
        out = await cdp.send("Runtime.evaluate", {
            "expression": AXE_SRC + f";axe.run(document,{opts}).then(r=>JSON.stringify(r))",
            "contextId": ctx_id, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in out:
            raise RuntimeError("axe_failed")
        dupes = await _dupes(cdp, ctx_id)  # same world: axe is still loaded
    finally:
        await cdp.detach()
    res = json.loads(out["result"]["value"])
    if not (res["violations"] or res["passes"] or res["incomplete"]):
        raise ValueError("scan_tampered")  # a real page always yields some result
    findings: list[Finding] = []
    tested: set[str] = set()
    for key in ("violations", "passes", "incomplete"):
        for rule in res[key]:
            wcag = from_axe_tags(rule["tags"])
            tested.update(wcag)
            if key == "passes":
                continue
            if key == "incomplete":
                status = "needs_review"
            else:
                status = "needs_author" if rule["id"] == "image-alt" else "fail"
            for node in rule["nodes"]:
                data = next((a["data"] for a in node["any"] if a.get("data")), {})
                t = node["target"]
                sel, msg, st = t[0], rule["help"], status
                if len(t) > 1 or not isinstance(sel, str):  # iframe or shadow path
                    sel = sel if isinstance(sel, str) else sel[0]
                    msg = f"{msg} [target: {json.dumps(t)[:300]}]"
                    st, data = "needs_review", {**data, "nested": True}
                findings.append(Finding(
                    rule_id=rule["id"], source="axe", status=st,
                    impact=node.get("impact") or rule.get("impact"),
                    selector=sel, wcag=wcag, message=msg, data=data,
                ))
    return findings + dupes, sorted(tested)
