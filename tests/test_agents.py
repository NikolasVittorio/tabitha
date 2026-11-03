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
