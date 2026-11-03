import asyncio
import logging

import pytest
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

import agents.subagents as subagents
from agents.lead import BUSY, make_lead
from gate.models import FixRequest, ScanRequest, WalkRequest

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
