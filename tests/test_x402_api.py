import asyncio
import base64
import json

import httpx
import pytest
from eth_account import Account
from x402 import x402Client
from x402.http.clients.httpx import x402_httpx_transport
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner
from x402.schemas import SettleResponse, SupportedKind, SupportedResponse, VerifyResponse

from gate.models import Fix
from gate.report import build_report
from gate.x402_api import LIVE_NETWORK, NETWORK, PRICE, make_app, settings

PAY_TO = "0x000000000000000000000000000000000000dEaD"
PAGE = "https://example.com/"


class Facilitator:
    """Real signed payloads reach this; only the on-chain part is faked."""

    def __init__(self, valid=True, settles=True):
        self.valid, self.settles, self.verified, self.settled = valid, settles, [], []

    def get_supported(self):
        return SupportedResponse(kinds=[SupportedKind(x402_version=2, scheme="exact", network=NETWORK)])

    async def verify(self, payload, requirements, **_):
        self.verified.append((payload, requirements))
        return VerifyResponse(is_valid=self.valid, payer="0xabc", invalid_reason=None if self.valid else "bad")

    async def settle(self, payload, requirements, **_):
        self.settled.append((payload, requirements))
        return SettleResponse(success=self.settles, transaction="0xtx", network=NETWORK, payer="0xabc",
                              error_reason=None if self.settles else "insufficient_funds")


def fixed_report(outcome="fixed"):
    return build_report("j", PAGE, [], [], fixes=[Fix(rule_id="r", selector="s", outcome=outcome, note="")], diff="d")


class Job:
    def __init__(self, result):
        self.result, self.urls = result, []

    async def __call__(self, url):
        self.urls.append(url)
        return self.result


def plain(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")


def paying(app):
    c = x402Client()
    register_exact_evm_client(c, EthAccountSigner(Account.create()), networks=NETWORK)
    return httpx.AsyncClient(transport=x402_httpx_transport(c, httpx.ASGITransport(app)), base_url="http://t", timeout=30)


async def test_unpaid_gets_402_with_terms_and_runs_nothing():
    f, job = Facilitator(), Job(fixed_report())
    async with plain(make_app(job, PAY_TO, f)) as c:
        r = await c.post("/fix", json={"url": PAGE})
    assert r.status_code == 402
    terms = json.loads(base64.b64decode(r.headers["payment-required"]))["accepts"][0]
    assert terms["payTo"] == PAY_TO and terms["network"] == NETWORK and terms["amount"] == "1000000"
    assert not job.urls and not f.verified and not f.settled


async def test_paid_fix_returns_report_and_settles_once():
    f, job = Facilitator(), Job(fixed_report())
    async with paying(make_app(job, PAY_TO, f)) as c:
        r = await c.post("/fix", json={"url": PAGE})
    assert r.status_code == 200 and r.json()["charged"] is True and r.json()["report"]["url"] == PAGE
    assert job.urls == [PAGE] and len(f.verified) == 1 and len(f.settled) == 1
    assert f.settled[0][1].pay_to == PAY_TO


async def test_nothing_is_charged_when_the_job_cannot_deliver():
    cases = [(build_report("j", PAGE, [], [], error="blocked"), 422, "blocked"),
             (fixed_report("not_fixed"), 422, "nothing_fixed"),
             (build_report("j", PAGE, [], []), 422, "nothing_fixed"),
             (None, 503, "busy")]
    for result, status, error in cases:
        f, job = Facilitator(), Job(result)
        async with paying(make_app(job, PAY_TO, f)) as c:
            r = await c.post("/fix", json={"url": PAGE})
        assert (r.status_code, r.json()["error"], r.json()["charged"]) == (status, error, False)
        assert len(f.verified) == 1 and not f.settled


async def test_bad_url_never_reaches_a_job_and_is_not_charged():
    for url, status in [("file:///etc/passwd", 400), ("x" * 2049, 422)]:
        f, job = Facilitator(), Job(fixed_report())
        async with paying(make_app(job, PAY_TO, f)) as c:
            r = await c.post("/fix", json={"url": url})
        assert r.status_code == status and not job.urls and not f.settled


async def test_invalid_payment_runs_nothing():
    f, job = Facilitator(valid=False), Job(fixed_report())
    async with paying(make_app(job, PAY_TO, f)) as c:
        r = await c.post("/fix", json={"url": PAGE})
    assert r.status_code == 402 and not job.urls and not f.settled


async def test_failed_settlement_withholds_the_report():
    f, job = Facilitator(settles=False), Job(fixed_report())
    async with paying(make_app(job, PAY_TO, f)) as c:
        r = await c.post("/fix", json={"url": PAGE})
    assert r.status_code == 402 and job.urls == [PAGE] and "report" not in r.text


KEYS = {"CDP_API_KEY_ID": "id", "CDP_API_KEY_SECRET": "secret"}


def test_real_money_only_when_asked_for_and_fully_configured():
    assert settings({})[0] == NETWORK and settings({**KEYS, "X402_PRICE": "$5.00"})[:2] == (NETWORK, PRICE)
    assert settings({**KEYS, "X402_LIVE": "1", "X402_PRICE": "$2.50"}) == (LIVE_NETWORK, "$2.50", "")
    for bad in ({"X402_LIVE": "1", "X402_PRICE": "$2.50"}, {**KEYS, "X402_LIVE": "1"},
                {**KEYS, "X402_LIVE": "1", "X402_PRICE": "2.50"}, {**KEYS, "X402_LIVE": "1", "X402_PRICE": "$0.00"}):
        with pytest.raises(ValueError):
            settings(bad)


async def test_job_over_the_time_limit_is_cancelled_and_not_charged(monkeypatch):
    monkeypatch.setattr("gate.x402_api.JOB_LIMIT_S", 0.01)
    cancelled = []

    async def slow(url):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(url)
            raise

    f = Facilitator()
    async with paying(make_app(slow, PAY_TO, f)) as c:
        r = await c.post("/fix", json={"url": PAGE})
    assert (r.status_code, r.json()["error"], r.json()["charged"]) == (504, "timeout", False)
    assert cancelled == [PAGE] and not f.settled
