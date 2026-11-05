import json
from datetime import date

import pytest
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, EndSessionContent, MetadataContent, TextContent
from uagents_core.contrib.protocols.payment import RequestPayment

import agents.lead as lead_mod
from gate.cards import NOT_NOW, NOT_NOW_REPLY, after_fix, intake, offer_fix
from gate.chat import Fix as FixAction, Reply, Scan, parse_chat
from gate.models import Finding, Fix
from gate.quota import Quota
from gate.report import build_report

URL = "https://e.com/a?b=1"
TESTED = ["1.1.1"]
F = Finding(rule_id="image-alt", source="axe", status="fail", impact="serious", selector="img", wcag=["1.1.1"], message="m")
REPORT = build_report("j", URL, [F], TESTED)
FIXED = build_report("j", URL, [F], TESTED, fixes=[Fix(rule_id="image-alt", selector="img", outcome="fixed", note="")])


def payload(card: MetadataContent) -> dict:
    assert all(isinstance(v, str) for v in card.metadata.values())
    assert card.metadata["card_protocol_version"] == "1" and card.metadata["requires_card_interaction"] == "true"
    assert len(card.metadata["card_payload"]) <= 64 * 1024
    return json.loads(card.metadata["card_payload"])


def parse(selection: dict):
    return parse_chat(json.dumps(selection), "alice", Quota(), date(2026, 11, 5))


def test_form_selection_reaches_the_right_action():
    form = payload(intake())
    assert {f["name"] for f in form["fields"]} == {"url", "mode"}
    assert all(f["options"] for f in form["fields"] if f["kind"] == "select")
    base = {**form["submit_cta"]["selection"], "url": "e.com"}
    assert parse({**base, "mode": "check"}) == Scan("https://e.com")
    assert parse({**base, "mode": "fix"}) == FixAction("https://e.com")


def test_review_buttons_reach_the_right_action():
    offer, done = payload(offer_fix(REPORT, "0.5")), payload(after_fix(FIXED))
    assert parse(offer["approve_cta"]["selection"]) == FixAction(URL)
    assert parse(done["approve_cta"]["selection"]) == Scan(URL)  # recheck is a free scan
    for p in (offer, done):
        assert NOT_NOW in json.dumps(p["reject_cta"]["selection"])
        assert isinstance(parse(p["reject_cta"]["selection"]), Reply)  # no URL: can never start a job
    assert {"label": "Automated issues", "value": "1 before, 0 after"} in done["summary_rows"]


def test_offer_states_price_and_payment_terms():
    rows = {r["label"]: r["value"] for r in payload(offer_fix(REPORT, "0.5"))["summary_rows"]}
    assert rows["Patch price"] == "0.5 FET" and "before the job runs" in rows["Payment"] and "by hand" in rows["Payment"]
    assert rows["Not tested"].startswith(str(len(REPORT.untested)))


def cards(msg):
    return [c for c in msg.content if isinstance(c, MetadataContent)]


def ends(msg):
    return any(isinstance(c, EndSessionContent) for c in msg.content)


class Ctx:
    import logging
    logger = logging.getLogger("test")

    def __init__(self):
        self.sent = []

    async def send(self, to, msg):
        self.sent.append((to, msg))


@pytest.fixture
def on_chat(monkeypatch):
    monkeypatch.setenv("FET_PAY_TO", "fetch1" + "q" * 38)
    monkeypatch.setenv("FET_PRICE", "0.5")
    monkeypatch.setenv("FET_REFUND_CONTACT", "help@example.com")
    return lambda: lead_mod.make_lead("seed", {"scan": "s", "walk": "w", "fix": "f"})._signed_message_handlers[
        Model.build_schema_digest(ChatMessage)]


async def say_to(handler, text):
    ctx = Ctx()
    await handler(ctx, "alice", ChatMessage(content=[TextContent(text=text)]))
    return ctx, ctx.sent[-1][1]


async def test_no_url_gets_answer_and_form(on_chat, monkeypatch):
    async def answer(*a): return "Hi"
    monkeypatch.setattr(lead_mod, "answer", answer)
    _, msg = await say_to(on_chat(), "what do you do?")
    assert msg.text() == "Hi" and cards(msg)[0].metadata["card_kind"] == "form" and not ends(msg)


async def test_scan_with_issues_offers_a_fix_alongside_the_full_report(on_chat, monkeypatch):
    async def gate(*a): return REPORT
    monkeypatch.setattr(lead_mod, "run_gate", gate)
    _, msg = await say_to(on_chat(), f"check {URL}")
    assert cards(msg)[0].metadata["card_kind"] == "review" and not ends(msg)
    assert REPORT.disclaimer in msg.text()  # the card never replaces the report


@pytest.mark.parametrize("report", [build_report("j", URL, [], TESTED), build_report("j", URL, [], [], error="timeout")])
async def test_nothing_to_sell_means_no_card(on_chat, monkeypatch, report):
    async def gate(*a): return report
    monkeypatch.setattr(lead_mod, "run_gate", gate)
    _, msg = await say_to(on_chat(), f"check {URL}")
    assert not cards(msg) and ends(msg)


async def test_no_card_offer_when_fet_is_off(on_chat, monkeypatch):
    async def gate(*a): return REPORT
    monkeypatch.setattr(lead_mod, "run_gate", gate)
    monkeypatch.delenv("FET_PAY_TO")
    _, msg = await say_to(on_chat(), f"check {URL}")
    assert not cards(msg)


async def test_not_now_runs_nothing(on_chat, monkeypatch):
    async def boom(*a): raise AssertionError("must not run")
    monkeypatch.setattr(lead_mod, "run_gate", boom)
    monkeypatch.setattr(lead_mod, "answer", boom)
    # direct JSON, and the planner's prose version even when it mentions the page
    for text in (json.dumps({"action": NOT_NOW}), f"The user picked {NOT_NOW} for {URL}"):
        ctx, msg = await say_to(on_chat(), text)
        assert msg.text() == NOT_NOW_REPLY and ends(msg)


async def test_get_a_patch_button_asks_for_payment_and_runs_nothing(on_chat, monkeypatch):
    async def boom(*a): raise AssertionError("a button must not skip payment")
    monkeypatch.setattr(lead_mod, "run_gate", boom)
    selection = json.loads(offer_fix(REPORT, "0.5").metadata["card_payload"])["approve_cta"]["selection"]
    ctx, _ = await say_to(on_chat(), json.dumps(selection))
    assert any(isinstance(m, RequestPayment) for _, m in ctx.sent)
