import asyncio
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent, chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, CompletePayment, Funds, RejectPayment, RequestPayment, payment_protocol_spec,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from uagents_core.identity import Identity

from agents.rpc import Pending
from agents.subagents import make_fixer, make_scanner, make_walker
from gate.history import History
from gate.chat import QUOTA_REPLY, Fix, Reply, parse_chat
from gate.models import A11yCheckRequest, FixResult, Report, ScanResult, WalkResult
from gate.payment import PRICE_AFET, dorado_get_tx, verify_fet_payment
from gate.pipeline import run_gate
from gate.quota import Quota
from gate.receipt import sign_receipt
from gate.report import build_report, render_chat

NAME = "A11y Gate Accessibility Check"
DESCRIPTION = ("Check a website for accessibility problems before it goes live: WCAG 2.2 AA scan, keyboard test "
               "and screen reader issues, with re-checked code fixes for AI agents and developers.")
PROFILE = Path(__file__).with_name("profile.md")  # published to Agentverse when the mailbox connects
BUSY = "Busy — try again in a minute."
NO_RECEIPT = "signed scan log unavailable (no signing key configured)"
WINDOW = 300  # seconds a payment reference stays valid
FREE_FIX = "payment disabled for the event"
TYPED_DIFF_CAP = 50_000
PAY_OVER_CHAT = "send `fix <url>` over the Chat Protocol to pay 0.5 TEST FET"


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


def make_lead(seed: str, sub_addrs: dict[str, str], get_tx=dorado_get_tx) -> Agent:
    """sub_addrs: {"scan": addr, "walk": addr, "fix": addr}. get_tx: blocking tx lookup (tests inject a fake)."""
    # concurrent: the chat handler awaits subagent replies that arrive on this same agent
    agent = Agent(name=NAME, seed=seed, mailbox=True, handle_messages_concurrently=True,
                  readme_path=str(PROFILE), description=DESCRIPTION)
    pending, quota, history = Pending(), Quota(), History()
    receipt_sk = receipt_key()
    sem = asyncio.Semaphore(2)  # at most 2 jobs in flight; the rest get BUSY, not a queue
    chat = Protocol(spec=chat_protocol_spec)
    pay = Protocol(spec=payment_protocol_spec, role="seller")
    check_proto = Protocol(name="a11y_gate_check", version="0.1.0")
    paid_on = os.environ.get("PAYMENT_ENABLED", "1") != "0"
    pay_to = str(agent.wallet.address())  # Dorado address the buyer pays
    # ponytail: in memory, lost on restart (like the quota); a restart drops unpaid jobs and the replay set
    pending_payments: dict[str, dict] = {}  # job_id -> {sender, url, deadline, timer}
    used_tx: set[str] = set()

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

    def with_delta(sender: str, r: Report) -> Report:
        d = history.compare(sender, r.url, r, datetime.now(timezone.utc))
        return r.copy(update={"delta": d}) if d else r

    async def admit(ctx: Context, sender: str, today, url: str, is_fix: bool, charge: bool) -> Report | str:
        """Admission shared by chat and typed callers: a Report, or "quota_exceeded" / "busy".
        charge=False when the quota was already taken (parse_chat charges chat scans)."""
        if charge and not quota.allow(sender, today):
            return "quota_exceeded"
        if sem.locked():  # no await between this check and `async with`, so no race
            quota.refund(sender, today)  # rejected work is not charged
            return "busy"
        async with sem:
            return with_delta(sender, await run_job(ctx, str(uuid4()), url, is_fix))

    async def say(ctx: Context, to: str, text: str, end: bool = True):
        await ctx.send(to, ChatMessage(content=[TextContent(text=text)] + ([EndSessionContent()] if end else [])))

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

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        today = datetime.now(timezone.utc).date()
        action = parse_chat(msg.text(), sender, quota, today)
        is_fix = isinstance(action, Fix)
        if is_fix and paid_on:  # no quota: the fix runs once paid, in on_commit
            job_id = str(uuid4())
            until = (datetime.now(timezone.utc) + timedelta(seconds=WINDOW)).strftime("%H:%M:%S UTC")
            pending_payments[job_id] = {"sender": sender, "url": action.url, "deadline": time.monotonic() + WINDOW,
                                        "until": until, "timer": asyncio.create_task(expire(ctx, job_id))}
            ctx.logger.info(f"job {job_id} payment requested")
            await ctx.send(sender, RequestPayment(
                accepted_funds=[Funds(currency="FET", amount="0.5", payment_method="fet_direct")],
                recipient=pay_to, deadline_seconds=WINDOW, reference=job_id,
                description=f"TEST — a11y patch + signed scan log. Set the tx memo to {job_id} (the reference)."))
            await say(ctx, sender, f"Payment requested: 0.5 TEST FET to {pay_to} on Dorado testnet "
                                   f"with tx memo {job_id}, within {WINDOW} s.", end=False)
            return
        if isinstance(action, Reply):
            return await say(ctx, sender, action.text)
        # payment off: a fix rides the free scan quota; a scan was already charged by parse_chat
        r = await admit(ctx, sender, today, action.url, is_fix, charge=is_fix)
        if isinstance(r, str):
            text = QUOTA_REPLY if r == "quota_exceeded" else BUSY
        else:
            text = f"{FREE_FIX}\n\n{render_chat(r, agents=sub_addrs)}" if is_fix else render_chat(r, agents=sub_addrs)
        await say(ctx, sender, text)

    @check_proto.on_message(A11yCheckRequest, replies=Report)
    async def on_check(ctx: Context, sender: str, msg: A11yCheckRequest):
        job_id, url = str(uuid4()), msg.url
        if not (isinstance(url, str) and len(url) <= 2048 and url.startswith(("http://", "https://"))):
            return await ctx.send(sender, build_report(job_id, "", [], [], error="bad_request"))  # never echo it
        if msg.mode == "fix" and paid_on:  # payment runs over chat only; a typed fix never runs unpaid
            r = build_report(job_id, url, [], [], error="payment_required")
            return await ctx.send(sender, r.copy(update={"note": PAY_OVER_CHAT}))
        r = await admit(ctx, sender, datetime.now(timezone.utc).date(), url, msg.mode == "fix", charge=True)
        if isinstance(r, str):
            r = build_report(job_id, url, [], [], error=r)
        elif len(r.diff) > TYPED_DIFF_CAP:  # the diff is not in the signed receipt payload
            cut = f"diff truncated at {TYPED_DIFF_CAP} characters"
            r = r.copy(update={"diff": r.diff[:TYPED_DIFF_CAP], "note": "; ".join(x for x in (r.note, cut) if x)})
        await ctx.send(sender, r)

    @pay.on_message(CommitPayment)
    async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
        job_id, tx_hash = msg.reference or "", msg.transaction_id

        async def check():
            """The sender's own open job; closes it (terminal) if its deadline passed; None = not usable."""
            p = pending_payments.get(job_id)
            if not p or p["sender"] != sender:  # a stranger can't touch someone else's reference
                # never terminal: only close() ends a session, and it runs once per reference
                await say(ctx, sender, "Unknown or closed payment reference.", end=False)
                return None
            if time.monotonic() >= p["deadline"]:
                await close(ctx, job_id, "payment window expired")
                return None
            return p

        async def retry(why: str):  # NON-terminal: the reference stays open until its deadline
            await say(ctx, sender, f"Payment not accepted: {why}. Fix it and resend CommitPayment "
                                   f"before {p['until']}.", end=False)

        if not (p := await check()):
            return
        ctx.logger.info(f"job {job_id} tx={tx_hash}")  # the hash only, never tx contents
        try:
            tx = await asyncio.to_thread(get_tx, tx_hash)  # blocking query, off the event loop
        except Exception:
            return await retry("transaction lookup failed")
        if tx is None:  # not indexed yet or chain unreachable: keep the job and its timer
            return await say(ctx, sender, "transaction not found yet - resend CommitPayment", end=False)
        # The job may have expired or been paid during the lookup. If it is still the same open job,
        # there is no await from the deadline check through verify (check-and-add `used_tx`) to the pop.
        if pending_payments.get(job_id) is not p or time.monotonic() >= p["deadline"]:
            return await check()
        if not verify_fet_payment(tx_hash, pay_to, PRICE_AFET, lambda _: tx, used_tx, job_id):
            return await retry("memo must equal the payment reference" if tx.get("memo") != job_id else
                               "transaction failed, below 0.5 TEST FET, wrong recipient or already used")
        del pending_payments[job_id]
        p["timer"].cancel()
        # ponytail: in-memory, testnet only; a restart mid-job loses the paid job. Persist before real money.
        async with sem:  # paid jobs wait for a slot instead of getting BUSY
            r = with_delta(sender, await run_job(ctx, job_id, p["url"], True))
        await say(ctx, sender, render_chat(r, agents=sub_addrs))
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


def main() -> None:
    # Seeds come from the environment only (python-dotenv is not installed; export them or
    # load .env in your shell). Seeds are never logged.
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
