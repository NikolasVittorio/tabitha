import asyncio

import aiohttp
import pytest

from gate import talk
from gate.talk import FALLBACK, answer, safe


async def test_no_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("ASI_ONE_API_KEY", raising=False)
    assert await answer("hi", "facts") == FALLBACK


@pytest.mark.parametrize("err", [aiohttp.ClientError(), asyncio.TimeoutError(), KeyError("choices"), ValueError()])
async def test_api_failure_uses_fallback(monkeypatch, err):
    async def boom(*a):
        raise err
    monkeypatch.setenv("ASI_ONE_API_KEY", "k")
    monkeypatch.setattr(talk, "_ask", boom)
    assert await answer("hi", "facts") == FALLBACK


async def test_safe_reply_is_returned_and_unsafe_is_not(monkeypatch):
    replies = ["Yes, a bare domain works.", "Your page is compliant."]
    async def ask(*a):
        return replies.pop(0)
    monkeypatch.setenv("ASI_ONE_API_KEY", "k")
    monkeypatch.setattr(talk, "_ask", ask)
    assert await answer("can i send a domain?", "facts") == "Yes, a bare domain works."
    assert await answer("is it ok?", "facts") == FALLBACK


@pytest.mark.parametrize("bad", [
    "", "x" * 601, "Your page passes.", "It meets WCAG.", "Pay at https://evil.example", "Visit www.evil.example",
    "Send funds to fetch1abc", "I scanned your page.", "I've tested it.", "I have just checked it.", "It is certified.",
])
def test_safety_check_rejects(bad):
    assert not safe(bad)


@pytest.mark.parametrize("good", ["Send `check example.com` and I'll test the page.", "Yes, a bare domain works.", FALLBACK])
def test_safety_check_allows(good):
    assert safe(good)


@pytest.mark.parametrize("bad", [
    "No, you are not charged if the fix fails.",
    "A fix costs 0.15 USDC over x402 or real FET in chat, charged only if a fix is confirmed.",
    "You are only charged if a fix is confirmed.",
    "There is no charge if the fix fails.",
    "Fixes cost real FET in chat. You are not charged if the fix fails.",
])
def test_safety_check_rejects_a_no_charge_claim_that_could_reach_a_fet_buyer(bad):
    assert not safe(bad)


@pytest.mark.parametrize("good", [
    "Agents paying 0.15 USDC over x402 are charged only if a fix is confirmed.",
    "In chat, FET is paid before the job and refunded by hand if no fix is confirmed. "
    "Agents paying 0.15 USDC over x402 are charged only if a fix is confirmed.",
    "Over x402 you are not charged if the fix fails.",
])
def test_safety_check_allows_a_no_charge_claim_about_x402(good):
    assert safe(good)


def test_rules_state_the_fet_terms():
    assert "FET is paid before the job and refunded by hand if no fix is confirmed." in talk.RULES


@pytest.mark.parametrize("bad", [
    "You won't be charged if the fix fails.",
    "You wont be charged if the fix fails.",
    "You won’t be charged if the fix fails.",
    "You aren't charged if the fix fails.",
    "You will not be charged if the fix fails.",
    "It is free if the fix fails.",
    "There is no fee if the fix fails.",
    "You won't be charged over x402 or in FET if the fix fails.",
    "It is free if the fix fails in chat, or over x402.",
])
def test_safety_check_rejects_other_ways_of_saying_no_charge(bad):
    assert not safe(bad)


@pytest.mark.parametrize("good", [
    "Over x402 you won't be charged if the fix fails.",
    "Agents paying 0.15 USDC aren't charged if no fix is confirmed.",
    "It is free if the fix fails over x402.",
    "There is no fee if the fix fails when paying USDC.",
])
def test_safety_check_allows_those_about_x402(good):
    assert safe(good)


def test_fallback_states_the_fet_terms():
    assert FALLBACK == ("Hi, I'm Tabitha. I check websites for accessibility problems before they go live. "
                        "Send me a page, like `check example.com`, and I'll test it in a real browser, including with a keyboard. "
                        "It's free for 5 scans a day. I can also suggest fixes with `fix example.com` for a small fee, "
                        "paid in FET before the job runs and refunded by hand if no fix is confirmed.")
