from pathlib import Path

from playwright.async_api import Page

from gate.models import Finding
from gate.wcag import from_axe_tags

AXE = Path(__file__).parent / "vendor" / "axe.min.js"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


async def scan(page: Page) -> tuple[list[Finding], list[str]]:
    await page.add_script_tag(path=str(AXE))
    res = await page.evaluate(
        "tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})", TAGS
    )
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
                # ponytail: iframe/shadow targets are lists; keep only the outermost selector
                sel = node["target"][0]
                findings.append(Finding(
                    rule_id=rule["id"], source="axe", status=status,
                    impact=node.get("impact") or rule.get("impact"),
                    selector=sel if isinstance(sel, str) else str(sel),
                    wcag=wcag, message=rule["help"], data=data,
                ))
    return findings, sorted(tested)
