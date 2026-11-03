import json

from playwright.async_api import Page

from gate.models import Finding
from gate.wcag import from_axe_tags

TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


async def scan(page: Page) -> tuple[list[Finding], list[str]]:
    # axe is provisioned by browser._context's init script as window.__a11yAxeRun
    res = await page.evaluate(
        "tags => window.__a11yAxeRun(document, {runOnly: {type: 'tag', values: tags},"
        " rules: {'frame-tested': {enabled: true}}})", TAGS)
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
