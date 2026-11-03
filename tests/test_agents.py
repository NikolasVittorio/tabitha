import asyncio
import logging

import pytest
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

import agents.subagents as subagents
from agents.lead import BUSY, make_lead
from gate.models import A11yCheckRequest, FixRequest, Report, ScanRequest, ScanResult, WalkRequest, WalkResult

LEAD = "agent1lead"
SUBS = {"scan": "agent1scan", "walk": "agent1walk", "fix": "agent1fix"}


class Ctx:
    logger = logging.getLogger("test")

    def __init__(self):
        self.sent = []

    async def send(self, to, msg):
        self.sent.append((to, msg))


def handler(agent, model):
    return agent._protocol.signed_message_handlers[Model.build_schema_digest(model)]


@pytest.mark.parametrize("make,req", [
    (subagents.make_scanner, ScanRequest(job_id="j", url="https://e.com", html="<p>")),
    (subagents.make_walker, WalkRequest(job_id="j", url="https://e.com")),
    (subagents.make_fixer, FixRequest(job_id="j", html="<p>", findings=[], rules=None)),
])
async def test_subagents_ignore_foreign_senders(make, req, monkeypatch):
    def boom(*a, **k): raise AssertionError("browser or fixer touched")
    for name in ("open_page", "open_html", "fix"):
        monkeypatch.setattr(subagents, name, boom)
    ctx = Ctx()
    await handler(make("seed", LEAD), type(req))(ctx, "agent1stranger", req)
    assert ctx.sent == []


async def test_lead_busy_when_full():
    lead = make_lead("seed", SUBS)
    on_chat = lead._signed_message_handlers[Model.build_schema_digest(ChatMessage)]
    ctx = Ctx()
    jobs = [asyncio.create_task(on_chat(ctx, f"user{i}", ChatMessage(content=[TextContent(text="check https://e.com")])))
            for i in range(2)]  # two jobs that never get subagent replies hold both slots
    for _ in range(5):
        await asyncio.sleep(0)
    dispatched = [m for to, m in ctx.sent if to in SUBS.values()]
    assert len(dispatched) == 4
    await on_chat(ctx, "user9", ChatMessage(content=[TextContent(text="check https://e.com")]))
    assert ctx.sent[-1][0] == "user9" and ctx.sent[-1][1].text() == BUSY
    assert [m for to, m in ctx.sent if to in SUBS.values()] == dispatched
    for j in jobs:
        j.cancel()


async def test_busy_refunds_quota():
    lead = make_lead("seed", SUBS)
    on_chat = lead._signed_message_handlers[Model.build_schema_digest(ChatMessage)]
    ctx = Ctx()
    msg = lambda: ChatMessage(content=[TextContent(text="check https://e.com")])
    jobs = [asyncio.create_task(on_chat(ctx, f"user{i}", msg())) for i in range(2)]
    for _ in range(5):
        await asyncio.sleep(0)
    for _ in range(5):  # a whole day's quota worth of Busy replies
        await on_chat(ctx, "me", msg())
        assert ctx.sent[-1][1].text() == BUSY
    jobs[0].cancel()  # frees a slot
    await asyncio.gather(jobs[0], return_exceptions=True)
    before = len([1 for to, _ in ctx.sent if to in SUBS.values()])
    job = asyncio.create_task(on_chat(ctx, "me", msg()))
    for _ in range(5):
        await asyncio.sleep(0)
    assert len([1 for to, _ in ctx.sent if to in SUBS.values()]) == before + 2  # scan + walk dispatched
    for j in (jobs[1], job):
        j.cancel()


def test_refund_never_below_zero():
    from datetime import date
    from gate.quota import Quota
    q, d = Quota(limit=1), date(2026, 11, 4)
    q.refund("s", d)
    assert q.allow("s", d) and not q.allow("s", d)


# --- typed A11yCheckRequest protocol ---

def typed(lead):
    return lead._signed_message_handlers[Model.build_schema_digest(A11yCheckRequest)]


def req(url="https://e.com", mode="check"):
    return A11yCheckRequest(url=url, mode=mode)


def subs_sent(ctx):
    return [m for to, m in ctx.sent if to in SUBS.values()]


async def spin():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_typed_bad_url_rejected():
    ctx = Ctx()
    for url in ("file:///etc/passwd", "javascript:alert(1)", "https://e.com/" + "a" * 2048):
        await typed(make_lead("seed", SUBS))(ctx, "me", req(url))
        assert ctx.sent[-1][0] == "me" and ctx.sent[-1][1].error == "bad_request"
    assert subs_sent(ctx) == []


async def test_typed_fix_requires_payment(monkeypatch):
    monkeypatch.delenv("PAYMENT_ENABLED", raising=False)
    ctx = Ctx()
    await typed(make_lead("seed", SUBS))(ctx, "me", req(mode="fix"))
    r = ctx.sent[-1][1]
    assert r.error == "payment_required"
    assert r.note == "send `fix <url>` over the Chat Protocol to pay 0.5 TEST FET"
    assert subs_sent(ctx) == []


async def test_typed_shares_chat_quota():
    lead = make_lead("seed", SUBS)
    on_chat = lead._signed_message_handlers[Model.build_schema_digest(ChatMessage)]
    ctx = Ctx()
    for _ in range(5):  # one at a time so the semaphore never says Busy; subagents never reply
        job = asyncio.create_task(on_chat(ctx, "me", ChatMessage(content=[TextContent(text="check https://e.com")])))
        await spin()
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
    before = subs_sent(ctx)
    await typed(lead)(ctx, "me", req())
    assert ctx.sent[-1][0] == "me" and ctx.sent[-1][1].error == "quota_exceeded"
    assert subs_sent(ctx) == before


async def test_typed_busy_refunds_quota():
    lead = make_lead("seed", SUBS)
    ctx = Ctx()
    jobs = [asyncio.create_task(typed(lead)(ctx, f"user{i}", req())) for i in range(2)]
    await spin()
    before = subs_sent(ctx)
    for _ in range(6):  # more than a day's quota: each busy reply is refunded
        await typed(lead)(ctx, "me", req())
        assert ctx.sent[-1][1].error == "busy"
    assert subs_sent(ctx) == before
    jobs[0].cancel()
    await asyncio.gather(jobs[0], return_exceptions=True)
    job = asyncio.create_task(typed(lead)(ctx, "me", req()))
    await spin()
    assert len(subs_sent(ctx)) == len(before) + 2  # quota untouched: scan + walk dispatched
    for j in (jobs[1], job):
        j.cancel()


async def test_typed_check_roundtrip():
    lead = make_lead("seed", SUBS)
    ctx = Ctx()
    job = asyncio.create_task(typed(lead)(ctx, "me", req()))
    await spin()
    reqs = {to: m for to, m in ctx.sent if to in SUBS.values()}
    await handler(lead, ScanResult)(ctx, SUBS["scan"], ScanResult(
        job_id=reqs[SUBS["scan"]].job_id, findings=[], tested=["1.1.1"], html="<p>", error=None))
    await handler(lead, WalkResult)(ctx, SUBS["walk"], WalkResult(
        job_id=reqs[SUBS["walk"]].job_id, findings=[], focus_path=[], tested=[], error=None))
    await asyncio.wait_for(job, 5)
    to, r = ctx.sent[-1]
    assert to == "me" and isinstance(r, Report) and r.error is None and r.url == "https://e.com"


async def test_typed_diff_capped(monkeypatch):
    import agents.lead as lead_mod
    from gate.report import build_report
    monkeypatch.setenv("PAYMENT_ENABLED", "0")

    async def fake_gate(job_id, url, scan, walk, fix):
        return build_report(job_id, url, [], [], diff="x" * 60_000)
    monkeypatch.setattr(lead_mod, "run_gate", fake_gate)
    ctx = Ctx()
    await typed(make_lead("seed", SUBS))(ctx, "me", req(mode="fix"))
    r = ctx.sent[-1][1]
    assert len(r.diff) == 50_000 and "diff truncated at 50000 characters" in r.note


async def test_check_protocol_in_manifest():  # async: Agent() needs a running loop
    lead = make_lead("seed", SUBS)
    assert "a11y_gate_check" in [p.name for p in lead.protocols.values()]
