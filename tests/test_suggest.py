import json

import pytest

from gate import suggest
from gate.models import Fix
from gate.receipt import sign_receipt
from gate.report import build_report, render_chat

HTML = '<html><body><p>Latest news</p><a id="n" href="/news"><svg></svg></a><a id="s" href="/shop"><svg></svg></a><img id="i"></body></html>'
LINKS = [Fix(rule_id="link-name", selector=s, outcome="needs_author", note="n") for s in ("#n", "#s")]
OTHER = [Fix(rule_id="image-alt", selector="#i", outcome="needs_author", note="n"),
         Fix(rule_id="html-has-lang", selector="html", outcome="fixed", note="n")]


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("ASI_ONE_API_KEY", "k")
    seen = {}

    def reply_with(text):
        async def fake(system, user, key, max_tokens=200):
            seen["user"] = user
            if isinstance(text, Exception):
                raise text
            return text
        monkeypatch.setattr(suggest, "complete", fake)
        return seen
    return reply_with


async def test_suggestions_go_only_on_labels_left_for_the_author(model):
    seen = model(json.dumps(["Latest news", "Shop"]))
    out = await suggest.suggest_labels(HTML, LINKS + OTHER)
    assert [x.suggestion for x in out] == ["Latest news", "Shop", "", ""]
    assert [x.outcome for x in out] == ["needs_author", "needs_author", "needs_author", "fixed"]  # never applied
    assert "/news" in seen["user"] and "Latest news" in seen["user"]


@pytest.mark.parametrize("draft", ["", "x" * 61, "Go to https://evil.example", "This page is compliant", 7])
async def test_bad_drafts_are_dropped(model, draft):
    model(json.dumps([draft, "Shop"]))
    out = await suggest.suggest_labels(HTML, LINKS)
    assert [x.suggestion for x in out] == ["", "Shop"]


@pytest.mark.parametrize("reply", ["not json", json.dumps(["only one"]), json.dumps({"a": 1}), TimeoutError()])
async def test_model_failure_changes_nothing(model, reply):
    model(reply)
    assert await suggest.suggest_labels(HTML, LINKS) == LINKS


async def test_no_key_means_no_call(monkeypatch):
    monkeypatch.delenv("ASI_ONE_API_KEY", raising=False)
    assert await suggest.suggest_labels(HTML, LINKS) == LINKS


def test_suggestion_is_labelled_quoted_and_outside_the_signed_log():
    x = Fix(rule_id="link-name", selector="a", outcome="needs_author", note="n", suggestion="Buy `now`")
    r = build_report("j", "https://e.com", [], ["1.4.3"], fixes=[x])
    assert "AI suggestion, not checked: `` Buy `now` ``" in render_chat(r)
    assert "Buy" not in sign_receipt(r.copy(update={"input_sha256": "a" * 64}), "11" * 32, __import__("datetime").datetime(2026, 11, 5)).payload_json


def test_items_with_wording_are_listed_before_the_cap():
    images = [Fix(rule_id="image-alt", selector=f"#i{n}", outcome="needs_author", note="n") for n in range(30)]
    link = Fix(rule_id="link-name", selector="#last", outcome="needs_author", note="n", suggestion="Go to News")
    assert "Go to News" in render_chat(build_report("j", "https://e.com", [], ["1.4.3"], fixes=images + [link]))
