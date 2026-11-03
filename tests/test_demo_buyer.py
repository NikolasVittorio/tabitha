import pytest
from uagents_core.contrib.protocols.payment import Funds, RequestPayment

from agents.demo_buyer import MAX_COMMITS, payment_plan, should_resend


def req(**kw):
    base = dict(accepted_funds=[Funds(currency="FET", amount="0.5", payment_method="fet_direct")],
                recipient="fetch1abc", deadline_seconds=300, reference="job-1")
    return RequestPayment(**{**base, **kw})


def test_plan_uses_reference_as_memo_and_exact_atestfet():
    assert payment_plan(req()) == ("fetch1abc", 500000000000000000, "job-1")


def test_plan_rejects_missing_reference_or_fund():
    with pytest.raises(ValueError):
        payment_plan(req(reference=None))
    with pytest.raises(ValueError):
        payment_plan(req(accepted_funds=[Funds(currency="USDC", amount="1", payment_method="skyfire")]))


@pytest.mark.parametrize("amount", ["NaN", "inf", "-1", "0", "0.51", "1" * 40, "abc", ""])
def test_plan_rejects_bad_amounts(amount):
    with pytest.raises(ValueError):
        payment_plan(req(accepted_funds=[Funds(currency="FET", amount=amount, payment_method="fet_direct")]))


def test_plan_rejects_long_reference_and_accepts_smaller_amount():
    with pytest.raises(ValueError):
        payment_plan(req(reference="x" * 129))
    assert payment_plan(req(accepted_funds=[Funds(currency="FET", amount="0.25", payment_method="fet_direct")]))[1] == 250000000000000000


class Ctx:
    async def send(self, *a):
        pass


def run_requests(monkeypatch, senders, want=True):
    import asyncio
    import agents.demo_buyer as db
    calls = []
    monkeypatch.setattr(db, "pay", lambda *a: calls.append(a) or "HASH")

    async def go():
        agent = db.make_buyer("seed phrase for tests", "lead1", "http://x")  # needs a running loop
        agent.state["want"] = want
        for s in senders:
            await agent.on_request(Ctx(), s, req())
    asyncio.run(go())
    return calls


def test_wrong_sender_never_pays(monkeypatch):
    assert run_requests(monkeypatch, ["stranger"]) == []


def test_no_outstanding_fix_never_pays(monkeypatch):
    assert run_requests(monkeypatch, ["lead1"], want=False) == []


def test_pays_once_for_duplicate_requests(monkeypatch):
    assert len(run_requests(monkeypatch, ["lead1", "lead1"])) == 1


def test_resend_only_on_not_found_and_under_cap():
    assert should_resend("transaction not found yet - resend CommitPayment", 1)
    assert not should_resend("transaction not found yet - resend CommitPayment", MAX_COMMITS)
    assert not should_resend("Payment not accepted: memo must equal the payment reference.", 1)
