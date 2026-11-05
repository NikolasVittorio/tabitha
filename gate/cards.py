"""ASI:One Interactive Cards. A card only adds buttons: the full text reply always goes with it, and button presses
come back as chat messages that parse_chat already understands, so a card can never skip payment."""
import json

from uagents_core.contrib.protocols.chat import MetadataContent

from gate.models import Report
from gate.report import fixed_count

NOT_NOW = "tabitha_not_now"  # distinctive: it must survive ASI:One's planner rewording the selection into prose
NOT_NOW_REPLY = "Okay. Send `check <url>` any time."
PAY_FIRST = "Real FET on Fetch mainnet, paid before the job runs. If no fix is confirmed, refunds are made by hand."
# ponytail: measured on ASI:One: the payment card only shows when the personal AI delegates. Drop this if direct chat gets it.
HOW_TO_PAY = "In a new chat, ask your ASI:One assistant to use Tabitha to fix this page. It shows the payment card there."


def _card(kind: str, payload: dict) -> MetadataContent:
    # ponytail: no schema or 64 KB guard here; ASI:One falls back to the text sent alongside. tests/test_cards.py checks shape.
    return MetadataContent(metadata={"card_protocol_version": "1", "requires_card_interaction": "true",
                                     "card_kind": kind, "card_payload": json.dumps(payload)})


def _rows(rows: dict[str, str]) -> list[dict]:
    return [{"label": k, "value": v} for k, v in rows.items()]


def intake() -> MetadataContent:
    return _card("form", {
        "title": "Check a page for accessibility problems",
        "fields": [
            {"name": "url", "kind": "text", "label": "Page address", "required": True},
            {"name": "mode", "kind": "select", "label": "What should Tabitha do?", "required": True, "options": [
                {"value": "check", "label": "Scan it (free)"},
                {"value": "fix", "label": "Suggest a patch (paid)"}]}],
        "submit_cta": {"label": "Run", "selection": {"action": "tabitha_run"}}})


def offer_fix(r: Report, price: str) -> MetadataContent:
    keyboard = sum(f.source == "walker" and f.status == "fail" for f in r.findings)
    return _card("review", {
        "title": "Accessibility scan",
        "summary_rows": _rows({"Page": r.url, "Automated issues": str(r.violation_count),
                               "Keyboard test": f"{r.focus_count} focus stops, {keyboard} issues",
                               "Not tested": f"{len(r.untested)} criteria need a person",
                               "Patch can cover": f"up to {r.fixable} of {r.violation_count} issues",
                               "Patch price": f"{price} FET", "Payment": PAY_FIRST, "How to pay": HOW_TO_PAY}),
        "approve_cta": {"label": f"Get a patch for {price} FET", "primary": True,
                        "selection": {"action": "fix", "url": r.url}},
        "reject_cta": {"label": "Not now", "selection": {"action": NOT_NOW}}})


def after_fix(r: Report) -> MetadataContent:
    return _card("review", {
        "title": "Patch ready",
        "summary_rows": _rows({"Page": r.url,
                               "Automated issues": f"{r.violation_count} before, {r.violation_count - fixed_count(r)} after",
                               "Not tested": f"{len(r.untested)} criteria need a person",
                               "Next": "Review the patch, apply it, then recheck the page."}),
        "approve_cta": {"label": "Recheck the page", "primary": True, "selection": {"action": "recheck", "url": r.url}},
        "reject_cta": {"label": "Done", "selection": {"action": NOT_NOW}}})
