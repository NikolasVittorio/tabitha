import asyncio
import logging

from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent
from uagents_core.contrib.protocols.payment import CancelPayment, CommitPayment, CompletePayment, Funds, RequestPayment

import agents.lead as lead_mod
from gate.payment import verify_fet_payment, PRICE_AFET

TO = "fetch1lead"


def tx(code=0, to=TO, amt=PRICE_AFET, denom="atestfet"):
    return {"code": code, "messages": [{"@type": "/cosmos.bank.v1beta1.MsgSend", "to_address": to, "amount": [{"denom": denom, "amount": str(amt)}]}]}


def test_verify_cases():
    used = set()
    assert verify_fet_payment("h1", TO, PRICE_AFET, lambda h: tx(), used)
    assert not verify_fet_payment("h1", TO, PRICE_AFET, lambda h: tx(), used)   # replay
    assert not verify_fet_payment("h2", TO, PRICE_AFET, lambda h: tx(code=5), used)
    assert not verify_fet_payment("h3", TO, PRICE_AFET, lambda h: tx(to="fetch1other"), used)
    assert not verify_fet_payment("h4", TO, PRICE_AFET, lambda h: tx(amt=1), used)
    assert not verify_fet_payment("h5", TO, PRICE_AFET, lambda h: None, used)
    assert not verify_fet_payment("h6", TO, PRICE_AFET, lambda h: tx(denom="afet"), used)
    assert used == {"h1"}  # failures never burn a hash


SUBS = {"scan": "agent1scan", "walk": "agent1walk", "fix": "agent1fix"}


class Ctx:
    logger = logging.getLogger("test")

    def __init__(self):
        self.sent = []

    async def send(self, to, msg):
        self.sent.append((to, msg))


def setup(get_tx=lambda h: None):
    agent = lead_mod.make_lead("seed", SUBS, get_tx=get_tx)
    h = lambda m: agent._signed_message_handlers[Model.build_schema_digest(m)]
    return agent, h(ChatMessage), h(CommitPayment), Ctx()


async def request(on_chat, ctx, sender):
    await on_chat(ctx, sender, ChatMessage(content=[TextContent(text="fix https://e.com")]))
    return [m for to, m in ctx.sent if to == sender and isinstance(m, RequestPayment)][-1]


def commit(req, tx_id):
    return CommitPayment(funds=Funds(amount="0.5", currency="FET"), recipient=req.recipient,
                         transaction_id=tx_id, reference=req.reference)


def dispatched(ctx):
    return [m for to, m in ctx.sent if to in SUBS.values()]


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_wrong_sender_rejected_then_owner_pays():
    agent, on_chat, on_commit, ctx = setup(lambda h: tx(to=str(agent.wallet.address())))
    req = await request(on_chat, ctx, "alice")
    assert req.recipient == str(agent.wallet.address()) and req.deadline_seconds == 300
    assert req.accepted_funds[0].amount == "0.5" and req.accepted_funds[0].payment_method == "fet_direct"
    assert dispatched(ctx) == []
    await on_commit(ctx, "mallory", commit(req, "h1"))
    assert isinstance(ctx.sent[-2][1], CancelPayment) and ctx.sent[-1][0] == "mallory"
    assert dispatched(ctx) == []
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))  # reference not consumed by mallory
    await settle()
    assert any(to == "alice" and isinstance(m, CompletePayment) for to, m in ctx.sent)
    assert len(dispatched(ctx)) == 2  # scan + walk
    job.cancel()


async def test_expired_reference_rejected(monkeypatch):
    monkeypatch.setattr(lead_mod, "WINDOW", 0)
    agent, on_chat, on_commit, ctx = setup(lambda h: tx(to=str(agent.wallet.address())))
    req = await request(on_chat, ctx, "alice")
    await on_commit(ctx, "alice", commit(req, "h1"))  # before the expiry timer even runs
    assert isinstance(ctx.sent[-2][1], CancelPayment)
    assert dispatched(ctx) == []
    req2 = await request(on_chat, ctx, "bob")
    await settle()  # timer fires: chat-only caller hears back
    assert ctx.sent[-1][0] == "bob" and "payment window expired" in ctx.sent[-1][1].text()
    await on_commit(ctx, "bob", commit(req2, "h2"))
    assert isinstance(ctx.sent[-2][1], CancelPayment) and dispatched(ctx) == []


async def test_replayed_hash_rejected_across_jobs():
    agent, on_chat, on_commit, ctx = setup(lambda h: tx(to=str(agent.wallet.address())))
    req1 = await request(on_chat, ctx, "alice")
    req2 = await request(on_chat, ctx, "alice")
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req1, "h1")))
    await settle()
    n = len(dispatched(ctx))
    await on_commit(ctx, "alice", commit(req2, "h1"))
    assert isinstance(ctx.sent[-2][1], CancelPayment) and "not verified" in ctx.sent[-1][1].text()
    assert len(dispatched(ctx)) == n
    await on_commit(ctx, "alice", commit(req1, "h9"))  # a reference is consumed once
    assert isinstance(ctx.sent[-2][1], CancelPayment)
    job.cancel()


async def test_payment_disabled_runs_free_on_scan_quota(monkeypatch):
    monkeypatch.setenv("PAYMENT_ENABLED", "0")

    async def fake_gate(job_id, url, scan, walk, fix):
        assert fix is not None
        raise RuntimeError("stop here")  # the fix path was reached without payment
    monkeypatch.setattr(lead_mod, "run_gate", fake_gate)
    agent, on_chat, on_commit, ctx = setup()
    reached = 0
    for _ in range(6):
        try:
            await on_chat(ctx, "alice", ChatMessage(content=[TextContent(text="fix https://e.com")]))
        except RuntimeError:
            reached += 1
    assert reached == 5  # 6th hits the free quota
    assert "Free scan limit" in ctx.sent[-1][1].text()
    assert not any(isinstance(m, RequestPayment) for _, m in ctx.sent)


async def test_payment_disabled_reply_is_labelled(monkeypatch):
    monkeypatch.setenv("PAYMENT_ENABLED", "0")
    from gate.models import Report

    async def fake_gate(job_id, url, scan, walk, fix):
        return Report(job_id=job_id, url=url, automated_status="no_automated_violations_detected", violation_count=0,
                      findings=[], tested=[], untested=[], fixes=[], diff="", disclaimer="", receipt=None, error="timeout")
    monkeypatch.setattr(lead_mod, "run_gate", fake_gate)
    agent, on_chat, on_commit, ctx = setup()
    await on_chat(ctx, "alice", ChatMessage(content=[TextContent(text="fix https://e.com")]))
    assert "payment disabled for the event" in ctx.sent[-1][1].text()
