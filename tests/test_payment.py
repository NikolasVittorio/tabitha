import asyncio
import logging

from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, EndSessionContent, TextContent
from uagents_core.contrib.protocols.payment import CancelPayment, CommitPayment, CompletePayment, Funds, RequestPayment

import agents.lead as lead_mod
from gate.payment import verify_fet_payment, PRICE_AFET

TO = "fetch1lead"
M = "job-1"


def tx(code=0, to=TO, amt=PRICE_AFET, denom="atestfet", memo=M):
    return {"code": code, "memo": memo, "messages": [{"@type": "/cosmos.bank.v1beta1.MsgSend", "to_address": to, "amount": [{"denom": denom, "amount": str(amt)}]}]}


def test_verify_cases():
    used = set()
    assert verify_fet_payment("h1", TO, PRICE_AFET, lambda h: tx(), used, M)
    assert not verify_fet_payment("h1", TO, PRICE_AFET, lambda h: tx(), used, M)   # replay
    assert not verify_fet_payment("h2", TO, PRICE_AFET, lambda h: tx(code=5), used, M)
    assert not verify_fet_payment("h3", TO, PRICE_AFET, lambda h: tx(to="fetch1other"), used, M)
    assert not verify_fet_payment("h4", TO, PRICE_AFET, lambda h: tx(amt=1), used, M)
    assert not verify_fet_payment("h5", TO, PRICE_AFET, lambda h: None, used, M)
    assert not verify_fet_payment("h6", TO, PRICE_AFET, lambda h: tx(denom="afet"), used, M)
    assert not verify_fet_payment("h7", TO, PRICE_AFET, lambda h: tx(memo="job-2"), used, M)  # memo mismatch
    assert not verify_fet_payment("h8", TO, PRICE_AFET, lambda h: tx(memo=""), used, "")  # no empty binding
    assert used == {"h1"}  # failures never burn a hash


SUBS = {"scan": "agent1scan", "walk": "agent1walk", "fix": "agent1fix"}


class Ctx:
    logger = logging.getLogger("test")

    def __init__(self):
        self.sent = []

    async def send(self, to, msg):
        self.sent.append((to, msg))


def setup(boom=()):
    chain, boom = {}, set(boom)  # tx hash -> tx dict; tests "confirm" txs by adding them

    def get_tx(h):
        if h in boom:  # a one-off lookup error (not grpc) for this hash
            boom.discard(h)
            raise ConnectionError("rpc down")
        return chain.get(h)
    agent = lead_mod.make_lead("seed", SUBS, get_tx=get_tx)
    h = lambda m: agent._signed_message_handlers[Model.build_schema_digest(m)]
    pay = lambda h_, req: chain.__setitem__(h_, tx(to=str(agent.wallet.address()), memo=req.reference))
    return pay, h(ChatMessage), h(CommitPayment), Ctx()


async def request(on_chat, ctx, sender):
    await on_chat(ctx, sender, ChatMessage(content=[TextContent(text="fix https://e.com")]))
    return [m for to, m in ctx.sent if to == sender and isinstance(m, RequestPayment)][-1]


def commit(req, tx_id):
    return CommitPayment(funds=Funds(amount="0.5", currency="FET"), recipient=req.recipient,
                         transaction_id=tx_id, reference=req.reference)


def dispatched(ctx):
    return [m for to, m in ctx.sent if to in SUBS.values()]


def completed(ctx, who):
    return any(to == who and isinstance(m, CompletePayment) for to, m in ctx.sent)


def nothing_terminal_before_complete(ctx, who):
    msgs = [m for to, m in ctx.sent if to == who]
    before = msgs[:[isinstance(m, CompletePayment) for m in msgs].index(True)]
    return not any(isinstance(m, CancelPayment) or (isinstance(m, ChatMessage) and
                   any(isinstance(c, EndSessionContent) for c in m.content)) for m in before)


def cancels(ctx, who):
    return sum(1 for to, m in ctx.sent if to == who and isinstance(m, CancelPayment))


async def settle():  # let handlers run, including the to_thread tx lookup
    for _ in range(20):
        await asyncio.sleep(0.01)


async def test_wrong_sender_rejected_then_owner_pays():
    pay, on_chat, on_commit, ctx = setup()
    req = await request(on_chat, ctx, "alice")
    assert req.deadline_seconds == 300 and req.reference in req.description
    assert req.accepted_funds[0].amount == "0.5" and req.accepted_funds[0].payment_method == "fet_direct"
    pay("h1", req)
    await on_commit(ctx, "mallory", commit(req, "h1"))
    assert isinstance(ctx.sent[-2][1], CancelPayment) and ctx.sent[-1][0] == "mallory"
    assert dispatched(ctx) == []
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))  # reference not consumed by mallory
    await settle()
    assert completed(ctx, "alice") and len(dispatched(ctx)) == 2  # scan + walk
    job.cancel()


async def test_two_senders_race_for_one_tx_memo_decides():
    pay, on_chat, on_commit, ctx = setup()
    ra, rb = await request(on_chat, ctx, "alice"), await request(on_chat, ctx, "bob")
    pay("h1", ra)  # alice's tx, memo = alice's job id, publicly visible on chain
    await on_commit(ctx, "bob", commit(rb, "h1"))  # bob claims it for his own job
    last = ctx.sent[-1][1].text()
    assert last.startswith("Payment not accepted: memo") and "resend CommitPayment before" in last
    assert not completed(ctx, "bob") and dispatched(ctx) == []
    job_a = asyncio.create_task(on_commit(ctx, "alice", commit(ra, "h1")))
    await settle()
    assert completed(ctx, "alice")
    pay("h2", rb)  # bob's job stayed open after the rejection; he can still pay
    job_b = asyncio.create_task(on_commit(ctx, "bob", commit(rb, "h2")))
    await settle()
    assert completed(ctx, "bob") and nothing_terminal_before_complete(ctx, "bob")
    job_a.cancel(), job_b.cancel()


async def test_lookup_error_then_same_hash_succeeds():
    pay, on_chat, on_commit, ctx = setup(boom={"h1"})
    req = await request(on_chat, ctx, "alice")
    pay("h1", req)
    await on_commit(ctx, "alice", commit(req, "h1"))  # lookup raises
    assert "Payment not accepted: transaction lookup failed" in ctx.sent[-1][1].text()
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))
    await settle()
    assert completed(ctx, "alice") and nothing_terminal_before_complete(ctx, "alice")
    job.cancel()


async def test_lookup_miss_is_retryable():
    pay, on_chat, on_commit, ctx = setup()
    req = await request(on_chat, ctx, "alice")
    await on_commit(ctx, "alice", commit(req, "h1"))  # not indexed yet
    assert "transaction not found yet - resend CommitPayment" in ctx.sent[-1][1].text()
    assert not any(isinstance(m, CancelPayment) for _, m in ctx.sent)
    pay("h1", req)
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))
    await settle()
    assert completed(ctx, "alice") and len(dispatched(ctx)) == 2
    job.cancel()


async def test_expired_reference_rejected(monkeypatch):
    monkeypatch.setattr(lead_mod, "WINDOW", 0)
    pay, on_chat, on_commit, ctx = setup()
    req = await request(on_chat, ctx, "alice")
    pay("h1", req)
    await on_commit(ctx, "alice", commit(req, "h1"))  # before the expiry timer even runs
    assert isinstance(ctx.sent[-2][1], CancelPayment) and dispatched(ctx) == []
    req2 = await request(on_chat, ctx, "bob")
    await settle()  # timer fires: chat-only caller hears back
    assert ctx.sent[-1][0] == "bob" and "payment window expired" in ctx.sent[-1][1].text()
    assert cancels(ctx, "bob") == 1 and cancels(ctx, "alice") == 1  # once each: commit-time and timer expiry
    pay("h2", req2)
    await on_commit(ctx, "bob", commit(req2, "h2"))
    assert isinstance(ctx.sent[-2][1], CancelPayment) and dispatched(ctx) == []


async def test_replayed_hash_rejected_across_jobs():
    pay, on_chat, on_commit, ctx = setup()
    req1, req2 = await request(on_chat, ctx, "alice"), await request(on_chat, ctx, "alice")
    pay("h1", req1)
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req1, "h1")))
    await settle()
    n = len(dispatched(ctx))
    await on_commit(ctx, "alice", commit(req2, "h1"))
    assert ctx.sent[-1][1].text().startswith("Payment not accepted") and cancels(ctx, "alice") == 0
    assert len(dispatched(ctx)) == n
    pay("h9", req1)
    await on_commit(ctx, "alice", commit(req1, "h9"))  # a reference is consumed once
    assert isinstance(ctx.sent[-2][1], CancelPayment) and len(dispatched(ctx)) == n
    job.cancel()


async def test_payment_disabled_runs_free_on_scan_quota(monkeypatch):
    monkeypatch.setenv("PAYMENT_ENABLED", "0")

    async def fake_gate(job_id, url, scan, walk, fix):
        assert fix is not None
        raise RuntimeError("stop here")  # the fix path was reached without payment
    monkeypatch.setattr(lead_mod, "run_gate", fake_gate)
    pay, on_chat, on_commit, ctx = setup()
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
    pay, on_chat, on_commit, ctx = setup()
    await on_chat(ctx, "alice", ChatMessage(content=[TextContent(text="fix https://e.com")]))
    assert "payment disabled for the event" in ctx.sent[-1][1].text()
