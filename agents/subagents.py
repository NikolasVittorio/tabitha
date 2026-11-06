import asyncio

from uagents import Agent, Context

from gate.browser import Blocked, open_html, open_page
from gate.fixer import fix
from gate.models import FixRequest, FixResult, ScanRequest, ScanResult, WalkRequest, WalkResult
from gate.scanner import aria_tree, scan
from gate.walker import walk

_KNOWN = {"too_large", "scan_tampered"}  # our own ValueError codes


def error_code(e: Exception) -> str:
    # never echo arbitrary exception text: it can carry page content
    if isinstance(e, Blocked):
        return "blocked"
    if isinstance(e, TimeoutError):
        return "timeout"
    if isinstance(e, ValueError) and str(e) in _KNOWN:
        return str(e)
    return "internal_error"


# Each subagent serves only the lead: other senders would skip the quota and chat validation.
def make_scanner(seed: str, lead_addr: str) -> Agent:
    agent = Agent(name="a11y_scanner", seed=seed, enable_agent_inspector=False)

    @agent.on_message(ScanRequest, replies=ScanResult)
    async def on_scan(ctx: Context, sender: str, req: ScanRequest):
        if sender != lead_addr:
            return
        try:
            findings, tree, skipped = None, "", []
            try:
                if req.html is not None:
                    html = req.html
                    async with open_html(html, req.url) as page:
                        findings, tested = await scan(page)
                        tree = await aria_tree(page)
                else:
                    async with open_page(req.url) as (page, html, skipped):
                        findings, tested = await scan(page)
                        tree = await aria_tree(page)
            except TimeoutError:
                if findings is None:
                    raise
                tree = ""  # the tree is optional: a stall after the scan keeps the findings
            res = ScanResult(job_id=req.job_id, findings=findings, tested=tested, html=html, error=None, tree=tree,
                             skipped=len(skipped))
        except Exception as e:
            res = ScanResult(job_id=req.job_id, findings=[], tested=[], html=None, error=error_code(e))
        await ctx.send(sender, res)

    return agent


def make_walker(seed: str, lead_addr: str) -> Agent:
    agent = Agent(name="a11y_walker", seed=seed, enable_agent_inspector=False)

    @agent.on_message(WalkRequest, replies=WalkResult)
    async def on_walk(ctx: Context, sender: str, req: WalkRequest):
        if sender != lead_addr:
            return
        try:
            async with open_page(req.url) as (page, _, skipped):
                findings, focus_path, tested = await walk(page)
            res = WalkResult(job_id=req.job_id, findings=findings, focus_path=focus_path, tested=tested, error=None,
                             skipped=len(skipped))
        except Exception as e:
            res = WalkResult(job_id=req.job_id, findings=[], focus_path=[], tested=[], error=error_code(e))
        await ctx.send(sender, res)

    return agent


def make_fixer(seed: str, lead_addr: str) -> Agent:
    agent = Agent(name="a11y_fixer", seed=seed, enable_agent_inspector=False)

    @agent.on_message(FixRequest, replies=FixResult)
    async def on_fix(ctx: Context, sender: str, req: FixRequest):
        if sender != lead_addr:
            return
        try:
            rules = set(req.rules) if req.rules is not None else None
            html, fixes = await asyncio.to_thread(fix, req.html, req.findings, rules)
        except Exception:
            # ponytail: FixResult has no error field; an unchanged page with no fixes means "nothing applied"
            html, fixes = req.html, []
        await ctx.send(sender, FixResult(job_id=req.job_id, patched_html=html, fixes=fixes))

    return agent
