import asyncio
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol, communication
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, CompletePayment, Funds, RejectPayment, RequestPayment, payment_protocol_spec,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from uagents_core.identity import Identity

from agents.rpc import Pending
from agents.subagents import make_fixer, make_scanner, make_walker
from gate.cards import NOT_NOW, NOT_NOW_REPLY, after_fix, intake, offer_fix
from gate.history import History
from gate.chat import FIX_URL, HELP, PAY_FIX, QUOTA_REPLY, USAGE, Fix, Reply, parse_chat
from gate.models import A11yCheckRequest, FixResult, Report, ScanResult, WalkResult
from gate.payment import fet_settings, fet_text, fetch_get_tx, job_amount, verify_fet_payment
from gate.pipeline import run_gate
from gate.quota import Quota
from gate.receipt import sign_receipt
from gate.report import build_report, render_chat
from gate.talk import FALLBACK, answer
from gate.x402_api import make_app, serve

NAME = "Tabitha - Accessibility Agent"
DESCRIPTION = ("Check websites for accessibility problems before launch: WCAG 2.2 AA scan, keyboard test, "
               "screen reader issues, re-checked code fixes for humans and AI agents.")
PROFILE = Path(__file__).with_name("profile.md")  # published to Agentverse when the mailbox connects
TALKS_PER_SENDER = 20  # a day; the model costs money and sender addresses are free
TALKS_TOTAL = 500
PRECHECKS_PER_SENDER = 10  # a day; each is a free scan, so `fix` can't be a way round the 5 free scans
BUSY = "Busy — try again in a minute."
PRECHECK_LIMIT = "Fix request limit reached for today (10 per UTC day). It resets at 00:00 UTC."
NOTHING_TO_PATCH = ("No automated issues found on {url}, so there is nothing to patch and you have not been charged. "
                    "Automated checks only cover part of accessibility.")
UNPATCHABLE = "A patch can't cover these, so you have not been charged. The list above is what to change."
NO_RECEIPT = "signed scan log unavailable (no signing key configured)"
WINDOW = 300  # seconds a payment reference stays valid
UNPAID = {"used": "this transaction was already used", "failed": "the transaction failed on chain",
          "wrong_recipient": "the transaction didn't pay the requested address",
          "low": "the transaction paid less than {price} FET"}
PAID_JOB_LIMIT_S = 300  # a paid job must always end in a reply


def receipt_key() -> str | None:
    """RECEIPT_KEY_HEX if it is a valid Ed25519 private key; logs only the public key."""
    key = os.environ.get("RECEIPT_KEY_HEX")
    try:
        pub = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key or "")).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    except ValueError:
        print("RECEIPT_KEY_HEX missing or invalid: fix reports go out unsigned", flush=True)
        return None
    print(f"TRUSTED_PUBKEY_HEX={pub}", flush=True)
    return key


def make_lead(seed: str, sub_addrs: dict[str, str], get_tx=fetch_get_tx) -> Agent:
    """sub_addrs: {"scan": addr, "walk": addr, "fix": addr}. get_tx: blocking tx lookup (tests inject a fake)."""
    # concurrent: the chat handler awaits subagent replies that arrive on this same agent
    agent = Agent(name=NAME, seed=seed, mailbox=True, handle_messages_concurrently=True,
                  readme_path=str(PROFILE), description=DESCRIPTION)
    pending, quota, history = Pending(), Quota(), History()
    receipt_sk = receipt_key()
    sem = asyncio.Semaphore(2)  # at most 2 jobs in flight; the rest get BUSY, not a queue
    chat = Protocol(spec=chat_protocol_spec)
    pay = Protocol(spec=payment_protocol_spec, role="seller")
    check_proto = Protocol(name="tabitha_check", version="0.1.0")
    try:
        fet = fet_settings(os.environ)
    except ValueError as e:  # fail closed: fixes stay on x402, and the rest of the agent keeps running
        print(f"FET payments off: {e}", flush=True)
        fet = None
    pay_note = PAY_FIX + (" Or send `fix <url>` over the Chat Protocol to pay in FET." if fet else "")
    # ponytail: in memory, lost on restart (like the quota). The memo stops a replay across a restart, but a job
    # paid just before a restart is lost, and is refunded by hand. Persist if paid volume ever matters.
    pending_payments: dict[str, dict] = {}  # job_id -> {sender, url, deadline, timer}
    used_tx: set[str] = set()
    flagged_tx: set[str] = set()  # unbound payments already flagged for a refund, so a resend can't flag twice

    def rpc(kind: str):
        async def call(ctx: Context, req):
            key = f"{kind}:{req.job_id}"  # scan and walk share a job id
            pending.create(key)
            await ctx.send(sub_addrs[kind], req)
            return await pending.wait(key)
        return call

    scan_rpc, walk_rpc, fix_rpc = rpc("scan"), rpc("walk"), rpc("fix")

    async def run_job(ctx: Context, job_id: str, url: str, is_fix: bool) -> Report:
        """Caller holds a semaphore slot."""
        ctx.logger.info(f"job {job_id} url_sha256={hashlib.sha256(url.encode()).hexdigest()}")
        r = await run_gate(job_id, url, lambda q: scan_rpc(ctx, q), lambda q: walk_rpc(ctx, q),
                           (lambda q: fix_rpc(ctx, q)) if is_fix else None)
        if is_fix and not r.error:
            try:
                r = r.copy(update={"receipt": sign_receipt(r, receipt_sk, datetime.now(timezone.utc))})
            except Exception:  # no key, or nothing to bind to: reply unsigned, never crash
                r = r.copy(update={"note": "; ".join(x for x in (r.note, NO_RECEIPT) if x)})
        ctx.logger.info(f"job {job_id} error={r.error} rules={sorted({f.rule_id for f in r.findings})}")
        return r

    if x402_to := os.environ.get("X402_PAY_TO"):
        @agent.on_event("startup")
        async def start_x402(ctx: Context):
            async def run_fix(url: str) -> Report | None:
                if sem.locked():  # no await before `async with`, so no race; busy is not charged
                    return None
                async with sem:
                    return await run_job(ctx, str(uuid4()), url, True)

            agent._x402_task = asyncio.create_task(serve(make_app(run_fix, x402_to)))  # keep a reference

    def with_delta(sender: str, r: Report) -> Report:
        d = history.compare(sender, r.url, r, datetime.now(timezone.utc))
        return r.copy(update={"delta": d}) if d else r

    async def admit(ctx: Context, sender: str, today, url: str, charge: bool) -> Report | str:
        """Admission shared by chat and typed callers: a Report, or "quota_exceeded" / "busy".
        charge=False when the quota was already taken (parse_chat charges chat scans)."""
        if charge and not quota.allow(sender, today):
            return "quota_exceeded"
        if sem.locked():  # no await between this check and `async with`, so no race
            quota.refund(sender, today)  # rejected work is not charged
            return "busy"
        async with sem:
            return with_delta(sender, await run_job(ctx, str(uuid4()), url, False))

    async def say(ctx: Context, to: str, text: str, card=None):
        """Every reply carries a card and no EndSessionContent. On ASI:One, replies with that marker and plain replies
        beyond a line stalled the send and never displayed, and sends go out one at a time, so one stall held up the
        rest. ponytail: measured behaviour, not documented; retest the bare reply if ASI:One changes."""
        started = time.monotonic()
        card = card or intake(terminal=True)
        status = await ctx.send(to, ChatMessage(content=[TextContent(text=text), card]))
        ctx.logger.info(f"reply {getattr(status, 'status', 'unknown')} in {time.monotonic() - started:.1f}s "
                        f"chars={len(text)} card={card.metadata['card_kind']}")

    async def close(ctx: Context, job_id: str, why: str):
        """The only place a reference closes unpaid: CancelPayment + end of chat session, once."""
        p = pending_payments.pop(job_id, None)
        if not p:
            return
        if p["timer"] is not asyncio.current_task():
            p["timer"].cancel()
        await ctx.send(p["sender"], CancelPayment(reason=why))
        await say(ctx, p["sender"], f"{why} (job {job_id}); no fix was run.")

    async def expire(ctx: Context, job_id: str):
        await asyncio.sleep(WINDOW)
        await close(ctx, job_id, "payment window expired")  # chat-only callers still hear back

    talks, all_talks = Quota(TALKS_PER_SENDER), Quota(TALKS_TOTAL)
    prechecks = Quota(PRECHECKS_PER_SENDER)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        if NOT_NOW in msg.text():  # before parsing: the planner's prose may repeat the page URL
            return await say(ctx, sender, NOT_NOW_REPLY)
        today = datetime.now(timezone.utc).date()
        action = parse_chat(msg.text(), sender, quota, today)
        if isinstance(action, Fix):  # never runs from chat alone: real FET here, or USDC over x402
            if not fet:
                return await say(ctx, sender, PAY_FIX)
            # Check the page for free before asking for money. Busy is tested first, so a busy reply costs no quota.
            if sem.locked():
                return await say(ctx, sender, BUSY)
            if not prechecks.allow(sender, today):
                return await say(ctx, sender, PRECHECK_LIMIT)
            async with sem:  # no await since the locked() check; released before the payment request
                r = await run_job(ctx, str(uuid4()), action.url, False)
            if r.error:
                return await say(ctx, sender, render_chat(r, agents=sub_addrs))
            if not r.violation_count:
                return await say(ctx, sender, NOTHING_TO_PATCH.format(url=r.url))
            if not r.fixable:
                return await say(ctx, sender, f"{render_chat(r, agents=sub_addrs)}\n\n{UNPATCHABLE}")
            job_id = str(uuid4())
            until = (datetime.now(timezone.utc) + timedelta(seconds=WINDOW)).strftime("%H:%M:%S UTC")
            afet = job_amount(fet.afet, {p["afet"] for p in pending_payments.values()})
            amount = fet_text(afet)
            pending_payments[job_id] = {"sender": sender, "url": action.url, "deadline": time.monotonic() + WINDOW,
                                        "until": until, "afet": afet, "timer": asyncio.create_task(expire(ctx, job_id))}
            ctx.logger.info(f"job {job_id} payment requested")
            terms = (f"Accessibility changes + signed scan log, paid in real FET on Fetch mainnet. Pay exactly {amount} "
                     f"FET to {fet.pay_to} within {WINDOW} s, or set the tx memo to {job_id} (the reference). If no fix "
                     f"is confirmed, the payment is refunded by hand: send the tx hash to {fet.refund_contact}.")
            await ctx.send(sender, RequestPayment(
                accepted_funds=[Funds(currency="FET", amount=amount, payment_method="fet_direct")],
                recipient=fet.pay_to, deadline_seconds=WINDOW, reference=job_id, description=terms,
                # ASI:One's payment card reads these keys, per Fetch's FET example; without them it fails the request
                metadata={"x402_url": FIX_URL, "provider_agent_wallet": fet.pay_to, "fet_network": "mainnet",
                          "mainnet": "true", "content": terms}))
            # ponytail: no chat text here. ASI:One's card needs the turn left on the request, as in Fetch's FET example.
            # A caller with no Payment Protocol support gets nothing until the window closes; add text if that matters.
            return
        if isinstance(action, Reply):
            if action.text != USAGE:
                return await say(ctx, sender, action.text)
            ok = talks.allow(sender, today) and all_talks.allow("all", today)
            return await say(ctx, sender, await answer(msg.text(), PROFILE.read_text()) if ok else FALLBACK, card=intake())
        r = await admit(ctx, sender, today, action.url, charge=False)  # parse_chat already charged the scan
        if isinstance(r, str):
            return await say(ctx, sender, QUOTA_REPLY if r == "quota_exceeded" else BUSY)
        offer = offer_fix(r, fet.price) if fet and r.fixable and not r.error else None
        await say(ctx, sender, render_chat(r, agents=sub_addrs), card=offer)

    @check_proto.on_message(A11yCheckRequest, replies=Report)
    async def on_check(ctx: Context, sender: str, msg: A11yCheckRequest):
        job_id, url = str(uuid4()), msg.url
        if not (isinstance(url, str) and len(url) <= 2048 and url.startswith(("http://", "https://"))):
            return await ctx.send(sender, build_report(job_id, "", [], [], error="bad_request"))  # never echo it
        if msg.mode == "fix":  # fixes are sold only over x402; a typed fix never runs
            r = build_report(job_id, url, [], [], error="payment_required")
            return await ctx.send(sender, r.copy(update={"note": pay_note}))
        r = await admit(ctx, sender, datetime.now(timezone.utc).date(), url, charge=True)
        if isinstance(r, str):
            r = build_report(job_id, url, [], [], error=r)
        await ctx.send(sender, r)

    @pay.on_message(CommitPayment)
    async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
        job_id, tx_hash = msg.reference or "", msg.transaction_id

        async def check():
            """The sender's own open job; closes it (terminal) if its deadline passed; None = not usable."""
            p = pending_payments.get(job_id)
            if not p or p["sender"] != sender:  # a stranger can't touch someone else's reference
                # never terminal: only close() ends a session, and it runs once per reference
                await say(ctx, sender, "Unknown or closed payment reference.")
                return None
            if time.monotonic() >= p["deadline"]:
                await close(ctx, job_id, "payment window expired")
                return None
            return p

        async def retry(why: str):  # NON-terminal: the reference stays open until its deadline
            await say(ctx, sender, f"Payment not accepted: {why}. Fix it and resend CommitPayment "
                                   f"before {p['until']}.")

        if not (p := await check()):
            return
        # a fixed flag, never metadata: its keys and values are both buyer-controlled
        ctx.logger.info(f"job {job_id} tx={tx_hash} buyer_wallet_sent={'buyer_fet_wallet' in (msg.metadata or {})}")
        try:
            tx = await asyncio.to_thread(get_tx, tx_hash)  # blocking query, off the event loop
        except Exception:
            return await retry("transaction lookup failed")
        if tx is None:  # not indexed yet or chain unreachable: keep the job and its timer
            return await say(ctx, sender, "transaction not found yet - resend CommitPayment")
        # The job may have expired or been paid during the lookup. If it is still the same open job,
        # there is no await from the deadline check through verify (check-and-add `used_tx`) to the pop.
        if pending_payments.get(job_id) is not p or time.monotonic() >= p["deadline"]:
            return await check()
        verdict = verify_fet_payment(tx_hash, fet.pay_to, fet.afet, lambda _: tx, used_tx, job_id, p["afet"])
        if verdict == "unbound":  # real money with nothing tying it to this job: a retry can't change a sent tx
            if tx_hash not in flagged_tx:
                flagged_tx.add(tx_hash)
                ctx.logger.warning(f"REFUND_DUE job {job_id} tx={tx_hash} reason=unbound")
            return await retry(f"this transaction isn't tied to this job. If you sent it for this job, send tx {tx_hash} "
                               f"to {fet.refund_contact} for a refund, or pay exactly {fet_text(p['afet'])} FET")
        if verdict != "ok":
            return await retry(UNPAID[verdict].format(price=fet_text(p["afet"])))
        del pending_payments[job_id]
        p["timer"].cancel()
        # Paid: from here every path must reply and must flag a refund if no fix was confirmed.
        why = None
        try:
            async with sem:  # paid jobs wait for a slot instead of getting BUSY
                r = with_delta(sender, await asyncio.wait_for(run_job(ctx, job_id, p["url"], True), PAID_JOB_LIMIT_S))
            text = render_chat(r, agents=sub_addrs)
            why = r.error or (None if any(f.outcome == "fixed" for f in r.fixes) else "nothing_fixed")
        except Exception as e:
            text, why = "Error: the job failed after payment.", type(e).__name__
        if why:
            ctx.logger.warning(f"REFUND_DUE job {job_id} tx={tx_hash} reason={why}")
            text += (f"\n\nYou paid, but no fix was confirmed ({why}). "
                     f"For a refund, send tx {tx_hash} to {fet.refund_contact}.")
        await say(ctx, sender, text, card=None if why else after_fix(r))
        await ctx.send(sender, CompletePayment(transaction_id=tx_hash))  # only after the report is delivered

    @pay.on_message(RejectPayment)
    async def on_reject(ctx: Context, sender: str, msg: RejectPayment):
        # RejectPayment carries no reference: drop every open request from this sender
        for job_id in [j for j, p in pending_payments.items() if p["sender"] == sender]:
            await close(ctx, job_id, "payment declined")

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat, publish_manifest=True)
    agent.include(pay, publish_manifest=True)
    agent.include(check_proto, publish_manifest=True)

    def resolver(kind: str, model):
        @agent.on_message(model)
        async def on_result(ctx: Context, sender: str, msg):
            if sender == sub_addrs[kind]:  # drop forged replies
                pending.resolve(f"{kind}:{msg.job_id}", msg)

    resolver("scan", ScanResult)
    resolver("walk", WalkResult)
    resolver("fix", FixResult)
    return agent


def log_posts() -> None:
    """Times each POST alone. The "reply" log line also counts time queued behind earlier sends, and stops at the
    30 s send timeout while the POST keeps going. ponytail: replaces a library global; delete once the webhook stall
    is explained."""
    post = communication.send_exchange_envelope

    async def timed(envelope, endpoints, sync=False):
        started = time.monotonic()
        result = await post(envelope, endpoints, sync)
        print(f"post {getattr(result, 'status', 'sync')} in {time.monotonic() - started:.1f}s "
              f"bytes={len(envelope.payload or '')} digest={envelope.schema_digest[:16]}", flush=True)
        return result

    communication.send_exchange_envelope = timed


def main() -> None:
    # Seeds come from the environment only (python-dotenv is not installed; export them or
    # load .env in your shell). Seeds are never logged.
    log_posts()
    lead_addr = Identity.from_seed(os.environ["LEAD_SEED"], 0).address  # same derivation Agent uses
    subs = {"scan": make_scanner(os.environ["SCANNER_SEED"], lead_addr),
            "walk": make_walker(os.environ["WALKER_SEED"], lead_addr),
            "fix": make_fixer(os.environ["FIXER_SEED"], lead_addr)}
    lead = make_lead(os.environ["LEAD_SEED"], {k: a.address for k, a in subs.items()})
    assert lead.address == lead_addr
    for name, a in [("lead", lead), *subs.items()]:
        print(f"{name}: {a.address}", flush=True)
    # Bureau never calls Agent.start_server, which is what normally logs this link
    print("Inspector: https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8000"
          f"&address={lead.address}", flush=True)
    Bureau(agents=[lead, *subs.values()], port=8000).run()


if __name__ == "__main__":
    main()
