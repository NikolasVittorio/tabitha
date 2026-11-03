import json
from pathlib import Path

from playwright.async_api import Page

from gate.models import Finding
from gate.wcag import from_axe_tags

AXE_SRC = (Path(__file__).parent / "vendor" / "axe.min.js").read_text("utf-8")
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


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
    finally:
        await cdp.detach()
    if "exceptionDetails" in out:
        raise RuntimeError("axe_failed")
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
    return findings, sorted(tested)
