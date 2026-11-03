"""Demo buyer: asks the lead to `fix <url>`, pays 0.5 TEST FET on Dorado with the memo set to the
payment reference, commits the payment and prints each chat reply.

    python -m agents.demo_buyer <url>

Env (names only): BUYER_SEED, BUYER_WALLET_MNEMONIC, LEAD_ADDRESS. Never prints the mnemonic or keys.
Needs a mailbox (connect it via the Inspector link in the log) so the lead can reach this agent.
"""
import asyncio
import os
import sys
from decimal import Decimal

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent, chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, CompletePayment, Funds, RequestPayment, payment_protocol_spec,
)

DENOM = "atestfet"
MAX_COMMITS = 5
WAIT_S = 5  # pause before resending CommitPayment
NOT_YET = "transaction not found yet"


def payment_plan(req: RequestPayment) -> tuple[str, int, str]:
    """(recipient, amount in atestfet, memo) for a RequestPayment. Memo == reference, which the lead requires."""
    fund = next((f for f in req.accepted_funds if f.currency == "FET" and f.payment_method == "fet_direct"), None)
    if fund is None or not req.reference:
        raise ValueError("RequestPayment needs a FET fet_direct fund and a reference")
    return req.recipient, int(Decimal(fund.amount) * 10**18), req.reference


def should_resend(reply_text: str, attempts: int) -> bool:
    """Resend CommitPayment only on the lead's 'not found yet' reply, at most MAX_COMMITS sends in total."""
    return NOT_YET in reply_text.lower() and attempts < MAX_COMMITS


def pay(recipient: str, amount: int, memo: str) -> str:
    """Blocking: send TEST FET with the memo, wait for the tx to land, return its hash."""
    from cosmpy.aerial.client import LedgerClient, NetworkConfig
    from cosmpy.aerial.wallet import LocalWallet
    from cosmpy.crypto.address import Address
    wallet = LocalWallet.from_mnemonic(os.environ["BUYER_WALLET_MNEMONIC"], prefix="fetch")
    ledger = LedgerClient(NetworkConfig.fetchai_stable_testnet())
    tx = ledger.send_tokens(Address(recipient), amount, DENOM, wallet, memo=memo)  # send_tokens takes memo
    tx.wait_to_complete()
    return tx.tx_hash


def make_buyer(seed: str, lead: str, url: str) -> Agent:
    agent = Agent(name="a11y_demo_buyer", seed=seed, mailbox=True)
    chat = Protocol(spec=chat_protocol_spec)
    payp = Protocol(spec=payment_protocol_spec, role="buyer")
    state = {"commit": None, "sends": 0}

    async def commit(ctx: Context):
        state["sends"] += 1
        await ctx.send(lead, state["commit"])

    @agent.on_event("startup")
    async def start(ctx: Context):
        print(f"buyer: {agent.address}", flush=True)
        await asyncio.sleep(3)  # let the mailbox connect
        await ctx.send(lead, ChatMessage(content=[TextContent(text=f"fix {url}")]))

    @payp.on_message(RequestPayment)
    async def on_request(ctx: Context, sender: str, msg: RequestPayment):
        recipient, amount, memo = payment_plan(msg)
        print(f"paying {amount} {DENOM} to {recipient} with memo {memo}", flush=True)
        tx_hash = await asyncio.to_thread(pay, recipient, amount, memo)
        print(f"tx confirmed: {tx_hash}", flush=True)
        state["commit"] = CommitPayment(
            funds=Funds(amount=msg.accepted_funds[0].amount, currency="FET", payment_method="fet_direct"),
            recipient=recipient, transaction_id=tx_hash, reference=memo)
        await commit(ctx)

    @payp.on_message(CompletePayment)
    async def on_complete(ctx: Context, sender: str, msg: CompletePayment):
        print("payment accepted", flush=True)

    @payp.on_message(CancelPayment)
    async def on_cancel(ctx: Context, sender: str, msg: CancelPayment):
        print(f"payment cancelled: {msg.reason}", flush=True)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        text = msg.text()
        print(f"\n--- lead ---\n{text}\n", flush=True)
        if state["commit"] and should_resend(text, state["sends"]):
            await asyncio.sleep(WAIT_S)
            await commit(ctx)
        elif any(isinstance(c, EndSessionContent) for c in msg.content):
            os._exit(0)  # ponytail: hard exit; the demo has nothing to clean up

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat)
    agent.include(payp)
    return agent


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m agents.demo_buyer <url>")
    make_buyer(os.environ["BUYER_SEED"], os.environ["LEAD_ADDRESS"], sys.argv[1]).run()


if __name__ == "__main__":
    main()
