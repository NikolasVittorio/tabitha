import asyncio
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent, chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import (
    CommitPayment, Funds, RejectPayment, RequestPayment, payment_protocol_spec,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from uagents_core.identity import Identity

from agents.rpc import Pending
from agents.subagents import make_fixer, make_scanner, make_walker
from gate.history import History
from gate.chat import FIX_URL, FIX_USDC, PAY_FIX, QUOTA_REPLY, USAGE, Fix, Reply, parse_chat
from gate.models import A11yCheckRequest, FixResult, Report, ScanResult, WalkResult
from gate.pipeline import run_gate
from gate.quota import Quota
from gate.receipt import sign_receipt
from gate.report import build_report, render_chat
from gate.talk import FALLBACK, answer
from gate.x402_api import PAY_WINDOW_S, make_app, serve

NAME = "Tabitha - Accessibility Agent"
DESCRIPTION = ("Check websites for accessibility problems before launch: WCAG 2.2 AA scan, keyboard test, "
               "screen reader issues, re-checked code fixes for humans and AI agents.")
PROFILE = Path(__file__).with_name("profile.md")  # published to Agentverse when the mailbox connects
TALKS_PER_SENDER = 20  # a day; the model costs money and sender addresses are free
TALKS_TOTAL = 500
BUSY = "Busy — try again in a minute."
NO_RECEIPT = "signed scan log unavailable (no signing key configured)"


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


def make_lead(seed: str, sub_addrs: dict[str, str]) -> Agent:
    """sub_addrs: {"scan": addr, "walk": addr, "fix": addr}."""
    # concurrent: the chat handler awaits subagent replies that arrive on this same agent
    agent = Agent(name=NAME, seed=seed, mailbox=True, handle_messages_concurrently=True,
                  readme_path=str(PROFILE), description=DESCRIPTION)
    pending, quota, history = Pending(), Quota(), History()
    receipt_sk = receipt_key()
    sem = asyncio.Semaphore(2)  # at most 2 jobs in flight; the rest get BUSY, not a queue
    chat = Protocol(spec=chat_protocol_spec)
    pay = Protocol(spec=payment_protocol_spec, role="seller")
    check_proto = Protocol(name="tabitha_check", version="0.1.0")

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

    async def say(ctx: Context, to: str, text: str, end: bool = True):
        await ctx.send(to, ChatMessage(content=[TextContent(text=text)] + ([EndSessionContent()] if end else [])))

    talks, all_talks = Quota(TALKS_PER_SENDER), Quota(TALKS_TOTAL)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        today = datetime.now(timezone.utc).date()
        action = parse_chat(msg.text(), sender, quota, today)
        if isinstance(action, Fix):  # fixes are sold only over x402: nothing runs from chat
            if x402_to:
                await ctx.send(sender, RequestPayment(
                    accepted_funds=[Funds(currency="USDC", amount=FIX_USDC, payment_method="x402")],
                    recipient=x402_to, deadline_seconds=PAY_WINDOW_S, reference=str(uuid4()),
                    description=PAY_FIX, metadata={"x402_url": FIX_URL}))
            return await say(ctx, sender, PAY_FIX)
        if isinstance(action, Reply):
            if action.text != USAGE:
                return await say(ctx, sender, action.text)
            ok = talks.allow(sender, today) and all_talks.allow("all", today)
            return await say(ctx, sender, await answer(msg.text(), PROFILE.read_text()) if ok else FALLBACK)
        r = await admit(ctx, sender, today, action.url, charge=False)  # parse_chat already charged the scan
        if isinstance(r, str):
            text = QUOTA_REPLY if r == "quota_exceeded" else BUSY
        else:
            text = render_chat(r, agents=sub_addrs)
        await say(ctx, sender, text)

    @check_proto.on_message(A11yCheckRequest, replies=Report)
    async def on_check(ctx: Context, sender: str, msg: A11yCheckRequest):
        job_id, url = str(uuid4()), msg.url
        if not (isinstance(url, str) and len(url) <= 2048 and url.startswith(("http://", "https://"))):
            return await ctx.send(sender, build_report(job_id, "", [], [], error="bad_request"))  # never echo it
        if msg.mode == "fix":  # fixes are sold only over x402; a typed fix never runs
            r = build_report(job_id, url, [], [], error="payment_required")
            return await ctx.send(sender, r.copy(update={"note": PAY_FIX}))
        r = await admit(ctx, sender, datetime.now(timezone.utc).date(), url, charge=True)
        if isinstance(r, str):
            r = build_report(job_id, url, [], [], error=r)
        await ctx.send(sender, r)

    @pay.on_message(CommitPayment)
    async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
        await say(ctx, sender, f"Payment is taken over x402, not here. {PAY_FIX}", end=False)

    @pay.on_message(RejectPayment)
    async def on_reject(ctx: Context, sender: str, msg: RejectPayment):
        pass  # nothing is held open: no job runs until the x402 endpoint is paid

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
