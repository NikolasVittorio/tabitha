"""Runs the real scan, walk, fix and rescan on one URL in this process, with no agents, mailbox or payment.

    python scripts/quality_check.py <url> [--out reply.md]

Prints JSON: violations, outcomes, labels written, reply size and where each reply section starts."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gate.browser import open_html, open_page  # noqa: E402
from gate.fixer import LABEL_RULES, fix  # noqa: E402
from gate.models import FixResult, ScanResult, WalkResult  # noqa: E402
from gate.pipeline import run_gate  # noqa: E402
from gate.report import render_chat  # noqa: E402
from gate.scanner import aria_tree, scan  # noqa: E402
from gate.walker import walk  # noqa: E402

SECTIONS = ("**Fix these first**", "**Keyboard test", "**Not tested", "**Next:", "**Changes to make**", "**Fixes**",
            "Suggested patch", "Automated scan result", "Agents on this job", "What an AI agent sees")
AGENTS = {"scan": "agent1scan", "walk": "agent1walk", "fix": "agent1fix"}


async def main(url: str, out: str | None) -> dict:
    allow = frozenset({urlparse(url).hostname}) if urlparse(url).hostname == "127.0.0.1" else frozenset()

    async def do_scan(q):
        opener = open_html(q.html, q.url, allow_ips=allow) if q.html is not None else open_page(q.url, allow_ips=allow)
        async with opener as opened:
            page, html, skipped = (opened, q.html, []) if q.html is not None else opened
            findings, tested = await scan(page)
            tree = await aria_tree(page)
        return ScanResult(job_id=q.job_id, findings=findings, tested=tested, html=html, error=None, tree=tree,
                          skipped=len(skipped))

    async def do_walk(q):
        async with open_page(q.url, allow_ips=allow) as (page, _, skipped):
            findings, path, tested = await walk(page)
        return WalkResult(job_id=q.job_id, findings=findings, focus_path=path, tested=tested, error=None,
                          skipped=len(skipped))

    async def do_fix(q):
        html, fixes = fix(q.html, q.findings, set(q.rules) if q.rules is not None else None)
        return FixResult(job_id=q.job_id, patched_html=html, fixes=fixes)

    r = await run_gate("check", url, do_scan, do_walk, do_fix)
    reply = render_chat(r, agents=AGENTS)
    if out:
        Path(out).write_text(reply, encoding="utf-8")
    outcomes: dict[str, int] = {}
    for x in r.fixes:
        outcomes[f"{x.rule_id}:{x.outcome}"] = outcomes.get(f"{x.rule_id}:{x.outcome}", 0) + 1
    return {"url": url, "error": r.error, "status": r.automated_status, "violations": r.violation_count,
            "note": r.note, "outcomes": outcomes,
            "labels": [{"rule": x.rule_id, "outcome": x.outcome, "changes": getattr(x, "changes", {}), "note": x.note}
                       for x in r.fixes if x.rule_id in LABEL_RULES],
            "diff_chars": len(r.diff), "reply_chars": len(reply),
            "sections": {s: reply.find(s) for s in SECTIONS if s in reply}}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--out")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(asyncio.run(main(a.url, a.out)), indent=1))
