import asyncio
import logging

import pytest
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, EndSessionContent, TextContent
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, CompletePayment, Funds, RejectPayment, RequestPayment,
)

import agents.lead as lead_mod
from gate.models import Fix
from gate.payment import fet_settings, fet_text, job_amount, verify_fet_payment
from gate.report import build_report

TO = "fetch1" + "q" * 38
PRICE_AFET = 500000000000000000
M = "job-1"
ENV = {"FET_PAY_TO": TO, "FET_PRICE": "0.5", "FET_REFUND_CONTACT": "help@example.com"}


@pytest.fixture(autouse=True)
def fet_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


def test_settings():
    assert fet_settings({}) is None
    assert fet_settings(ENV) == (TO, "0.5", PRICE_AFET, "help@example.com")
    for bad in ({"FET_PAY_TO": "0xabc"}, {"FET_PAY_TO": ""}, {"FET_PRICE": "0"}, {"FET_PRICE": "-1"}, {"FET_PRICE": "NaN"},
                {"FET_PRICE": ""}, {"FET_REFUND_CONTACT": ""}):
        with pytest.raises(ValueError):
            fet_settings({**ENV, **bad})


def tx(code=0, to=TO, amt=PRICE_AFET, denom="afet", memo=M):
    return {"code": code, "memo": memo, "messages": [{"@type": "/cosmos.bank.v1beta1.MsgSend", "to_address": to, "amount": [{"denom": denom, "amount": str(amt)}]}]}


def test_verify_cases():
    used = set()
    v = lambda h, t, memo=M, exact=None: verify_fet_payment(h, TO, PRICE_AFET, lambda _: t, used, memo, exact)
    assert v("h1", tx()) == "ok"
    assert v("h1", tx()) == "used"  # replay
    assert v("h2", tx(code=5)) == "failed"
    assert v("h3", tx(to="fetch1other")) == "wrong_recipient"
    assert v("h4", tx(amt=1)) == "low"
    assert v("h5", None) == "failed"
    assert v("h6", tx(denom="atestfet")) == "wrong_recipient"  # test tokens are not money
    assert v("h7", tx(memo="job-2")) == "unbound"  # another job's memo
    assert v("h8", tx(memo=""), memo="") == "unbound"  # no empty binding
    assert used == {"h1"}  # failures never burn a hash


def test_exact_amount_binds_a_payment_with_no_memo():
    used, exact = set(), job_amount(PRICE_AFET, set())
    v = lambda h, amt: verify_fet_payment(h, TO, PRICE_AFET, lambda _: tx(amt=amt, memo=""), used, M, exact)
    assert v("h1", exact) == "ok" and used == {"h1"}
    assert v("h2", exact + 1) == "unbound" and v("h3", PRICE_AFET) == "unbound"  # near misses bind to nothing


def test_job_amounts_are_unique_exact_and_barely_above_the_price():
    taken = {job_amount(PRICE_AFET, set()) for _ in range(20)}
    a = job_amount(PRICE_AFET, taken)
    assert a not in taken and PRICE_AFET < a <= PRICE_AFET + 10**15  # at most 0.001 FET extra
    assert int(__import__("decimal").Decimal(fet_text(a)) * 10**18) == a


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
    pay = lambda h_, req: chain.__setitem__(h_, tx(to=TO, memo=req.reference))
    ctx = Ctx()
    ctx.on_reject = h(RejectPayment)
    return pay, h(ChatMessage), h(CommitPayment), ctx


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


def running_not_closed(ctx, who):
    """Payment accepted, job in flight: nothing terminal yet, and CompletePayment waits for the report."""
    return not completed(ctx, who) and cancels(ctx, who) == 0 and ends(ctx, who) == 0


def cancels(ctx, who):
    return sum(1 for to, m in ctx.sent if to == who and isinstance(m, CancelPayment))


def ends(ctx, who):
    return sum(1 for to, m in ctx.sent if to == who and isinstance(m, ChatMessage)
               and any(isinstance(c, EndSessionContent) for c in m.content))


UNKNOWN = "Unknown or closed payment reference."


async def settle():  # let handlers run, including the to_thread tx lookup
    for _ in range(20):
        await asyncio.sleep(0.01)


async def test_wrong_sender_rejected_then_owner_pays():
    pay, on_chat, on_commit, ctx = setup()
    req = await request(on_chat, ctx, "alice")
    assert req.deadline_seconds == 300 and req.reference in req.description
    assert req.accepted_funds[0].amount.startswith("0.50") and req.accepted_funds[0].payment_method == "fet_direct"
    assert req.metadata["fet_network"] == "mainnet" and req.accepted_funds[0].amount in req.description
    pay("h1", req)
    await on_commit(ctx, "mallory", commit(req, "h1"))
    assert ctx.sent[-1][0] == "mallory" and ctx.sent[-1][1].text() == UNKNOWN
    assert cancels(ctx, "mallory") == 0 and ends(ctx, "mallory") == 0
    assert dispatched(ctx) == []
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))  # reference not consumed by mallory
    await settle()
    assert running_not_closed(ctx, "alice") and len(dispatched(ctx)) == 2  # scan + walk
    job.cancel()


async def test_two_senders_race_for_one_tx_memo_decides():
    pay, on_chat, on_commit, ctx = setup()
    ra, rb = await request(on_chat, ctx, "alice"), await request(on_chat, ctx, "bob")
    pay("h1", ra)  # alice's tx, memo = alice's job id, publicly visible on chain
    await on_commit(ctx, "bob", commit(rb, "h1"))  # bob claims it for his own job
    last = ctx.sent[-1][1].text()
    assert last.startswith("Payment not accepted: this transaction isn't tied") and "resend CommitPayment before" in last
    assert "help@example.com" in last
    assert not completed(ctx, "bob") and dispatched(ctx) == []
    job_a = asyncio.create_task(on_commit(ctx, "alice", commit(ra, "h1")))
    await settle()
    assert running_not_closed(ctx, "alice") and len(dispatched(ctx)) == 2
    pay("h2", rb)  # bob's job stayed open after the rejection; he can still pay
    job_b = asyncio.create_task(on_commit(ctx, "bob", commit(rb, "h2")))
    await settle()
    assert running_not_closed(ctx, "bob") and len(dispatched(ctx)) == 4
    job_a.cancel(), job_b.cancel()


async def test_lookup_error_then_same_hash_succeeds():
    pay, on_chat, on_commit, ctx = setup(boom={"h1"})
    req = await request(on_chat, ctx, "alice")
    pay("h1", req)
    await on_commit(ctx, "alice", commit(req, "h1"))  # lookup raises
    assert "Payment not accepted: transaction lookup failed" in ctx.sent[-1][1].text()
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))
    await settle()
    assert running_not_closed(ctx, "alice") and len(dispatched(ctx)) == 2
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
    assert running_not_closed(ctx, "alice") and len(dispatched(ctx)) == 2
    job.cancel()


async def test_complete_payment_only_after_report_delivered(monkeypatch):
    async def fake_gate(job_id, url, *a):
        return build_report(job_id, url, [], [], error="timeout")
    monkeypatch.setattr(lead_mod, "run_gate", fake_gate)
    pay, on_chat, on_commit, ctx = setup()
    req = await request(on_chat, ctx, "alice")
    pay("h1", req)
    await on_commit(ctx, "alice", commit(req, "h1"))
    report, done = [m for to, m in ctx.sent if to == "alice"][-2:]
    assert isinstance(report, ChatMessage) and report.text().startswith("Error:")
    assert isinstance(done, CompletePayment) and done.transaction_id == "h1"
    assert "no fix was confirmed" in report.text() and "h1" in report.text() and "help@example.com" in report.text()


async def _paid(monkeypatch, gate, caplog):
    monkeypatch.setattr(lead_mod, "run_gate", gate)
    pay, on_chat, on_commit, ctx = setup()
    req = await request(on_chat, ctx, "alice")
    assert req.recipient == TO  # the owner's wallet, not the agent's
    pay("h1", req)
    with caplog.at_level(logging.WARNING):
        await on_commit(ctx, "alice", commit(req, "h1"))
    return [m for to, m in ctx.sent if to == "alice"][-2:]


async def test_confirmed_fix_owes_no_refund(monkeypatch, caplog):
    async def gate(job_id, url, *a):
        return build_report(job_id, url, [], [], fixes=[Fix(rule_id="r", selector="s", outcome="fixed", note="")], diff="d")
    report, done = await _paid(monkeypatch, gate, caplog)
    assert "refund" not in report.text() and isinstance(done, CompletePayment) and "REFUND_DUE" not in caplog.text


async def test_nothing_fixed_is_flagged_for_refund(monkeypatch, caplog):
    async def gate(job_id, url, *a):
        return build_report(job_id, url, [], [], fixes=[Fix(rule_id="r", selector="s", outcome="needs_author", note="")])
    report, done = await _paid(monkeypatch, gate, caplog)
    assert "refund" in report.text() and isinstance(done, CompletePayment) and "REFUND_DUE" in caplog.text


async def test_crash_after_payment_still_replies_and_flags_refund(monkeypatch, caplog):
    async def gate(job_id, url, *a):
        raise RuntimeError("boom")
    report, done = await _paid(monkeypatch, gate, caplog)
    assert "refund" in report.text() and isinstance(done, CompletePayment) and "REFUND_DUE" in caplog.text


async def test_fet_off_gives_x402_terms_and_never_requests_payment(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k)
    _, on_chat, _, ctx = setup()
    await on_chat(ctx, "alice", ChatMessage(content=[TextContent(text="fix https://e.com")]))
    assert ctx.sent[-1][1].text() == lead_mod.PAY_FIX and dispatched(ctx) == []
    assert not any(isinstance(m, RequestPayment) for _, m in ctx.sent)


async def test_bad_fet_config_turns_fet_off(monkeypatch):
    monkeypatch.setenv("FET_PAY_TO", "wrong")
    _, on_chat, _, ctx = setup()
    await on_chat(ctx, "alice", ChatMessage(content=[TextContent(text="fix https://e.com")]))
    assert not any(isinstance(m, RequestPayment) for _, m in ctx.sent)


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
    for _ in range(3):  # late commits on the closed reference are never terminal again
        await on_commit(ctx, "bob", commit(req2, "h2"))
        assert ctx.sent[-1][1].text() == UNKNOWN
    assert cancels(ctx, "bob") == 1 and ends(ctx, "bob") == 1 and dispatched(ctx) == []


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
    assert ctx.sent[-1][1].text() == UNKNOWN and len(dispatched(ctx)) == n
    job.cancel()


async def test_reject_twice_cancels_each_open_job_once():
    pay, on_chat, on_commit, ctx = setup()
    await request(on_chat, ctx, "alice"), await request(on_chat, ctx, "alice")
    for _ in range(2):
        await ctx.on_reject(ctx, "alice", RejectPayment(reason="no"))
    assert cancels(ctx, "alice") == 2 and ends(ctx, "alice") == 2  # one per open job, not per reject


async def test_message_with_no_url_goes_to_the_model_up_to_the_daily_cap(monkeypatch):
    seen = []
    async def fake(text, facts):
        seen.append(text)
        return 'model reply'
    monkeypatch.setattr(lead_mod, 'answer', fake)
    _, on_chat, _, ctx = setup()
    send = lambda text: on_chat(ctx, 'alice', ChatMessage(content=[TextContent(text=text)]))
    last = lambda: [m for _, m in ctx.sent if isinstance(m, ChatMessage)][-1].text()
    await send('what can you do')
    assert seen == ['what can you do'] and last() == 'model reply'
    for _ in range(lead_mod.TALKS_PER_SENDER - 1):
        await send('again')
    await send('one too many')
    assert 'one too many' not in seen and last() == lead_mod.FALLBACK


async def _pay_no_memo(amount_of):
    chain = {}
    agent = lead_mod.make_lead("seed", SUBS, get_tx=chain.get)
    h = lambda m: agent._signed_message_handlers[Model.build_schema_digest(m)]
    ctx = Ctx()
    req = await request(h(ChatMessage), ctx, "alice")
    chain["h1"] = tx(memo="", amt=amount_of(req))
    return ctx, req, h(CommitPayment)


async def test_exact_amount_with_no_memo_runs_the_job():
    ctx, req, on_commit = await _pay_no_memo(lambda r: int(__import__("decimal").Decimal(r.accepted_funds[0].amount) * 10**18))
    job = asyncio.create_task(on_commit(ctx, "alice", commit(req, "h1")))
    await settle()
    assert running_not_closed(ctx, "alice") and len(dispatched(ctx)) == 2
    job.cancel()


async def test_unbound_payment_flags_one_refund_and_runs_nothing(caplog):
    ctx, req, on_commit = await _pay_no_memo(lambda r: PRICE_AFET)
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            await on_commit(ctx, "alice", commit(req, "h1"))
    last = ctx.sent[-1][1].text()
    assert "for a refund" in last and "help@example.com" in last and "h1" in last
    assert caplog.text.count("REFUND_DUE") == 1 and dispatched(ctx) == [] and not completed(ctx, "alice")
