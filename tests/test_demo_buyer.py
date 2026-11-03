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


def test_resend_only_on_not_found_and_under_cap():
    assert should_resend("transaction not found yet - resend CommitPayment", 1)
    assert not should_resend("transaction not found yet - resend CommitPayment", MAX_COMMITS)
    assert not should_resend("Payment not accepted: memo must equal the payment reference.", 1)
