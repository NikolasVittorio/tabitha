import asyncio
import hashlib
import os
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Bureau, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent, chat_protocol_spec,
)
from uagents_core.identity import Identity

from agents.rpc import Pending
from agents.subagents import make_fixer, make_scanner, make_walker
from gate.chat import Reply, parse_chat
from gate.models import FixResult, ScanResult, WalkResult
from gate.pipeline import run_gate
from gate.quota import Quota
from gate.report import render_chat

BUSY = "Busy — try again in a minute."


def make_lead(seed: str, sub_addrs: dict[str, str]) -> Agent:
    """sub_addrs: {"scan": addr, "walk": addr, "fix": addr}."""
    # concurrent: the chat handler awaits subagent replies that arrive on this same agent
    agent = Agent(name="a11y_gate", seed=seed, mailbox=True, handle_messages_concurrently=True)
    pending, quota = Pending(), Quota()
    sem = asyncio.Semaphore(2)  # at most 2 jobs in flight; the rest get BUSY, not a queue
    chat = Protocol(spec=chat_protocol_spec)

    def rpc(kind: str):
        async def call(ctx: Context, req):
            key = f"{kind}:{req.job_id}"  # scan and walk share a job id
            pending.create(key)
            await ctx.send(sub_addrs[kind], req)
            return await pending.wait(key)
        return call

    scan_rpc, walk_rpc = rpc("scan"), rpc("walk")

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        action = parse_chat(msg.text(), sender, quota, datetime.now(timezone.utc).date())
        if isinstance(action, Reply):
            text = action.text
        elif sem.locked():  # no await between this check and `async with`, so no race
            text = BUSY
        else:  # ponytail: Fix(url) runs the scan+walk path until Task 9 adds payment and patching
            async with sem:
                job_id = str(uuid4())
                ctx.logger.info(f"job {job_id} url_sha256={hashlib.sha256(action.url.encode()).hexdigest()}")
                r = await run_gate(job_id, action.url, lambda q: scan_rpc(ctx, q), lambda q: walk_rpc(ctx, q), None)
                ctx.logger.info(f"job {job_id} error={r.error} rules={sorted({f.rule_id for f in r.findings})}")
            text = render_chat(r)
        await ctx.send(sender, ChatMessage(content=[TextContent(text=text), EndSessionContent()]))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat, publish_manifest=True)

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
