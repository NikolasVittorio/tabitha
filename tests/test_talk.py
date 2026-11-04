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
