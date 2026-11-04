"""Hire Tabitha over x402 with test USDC: python -m agents.x402_buyer <tabitha-url> <page-url>
Needs X402_BUYER_KEY, a throwaway key holding Base Sepolia USDC. It needs no ETH."""
import asyncio
import json
import os
import sys

from eth_account import Account
from x402 import x402Client
from x402.http.clients.httpx import x402HttpxClient
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner

from gate.x402_api import NETWORK


async def main(endpoint: str, page: str) -> None:
    client = x402Client()
    # one network only: this key can never sign a payment on a real-money chain
    register_exact_evm_client(client, EthAccountSigner(Account.from_key(os.environ["X402_BUYER_KEY"])), networks=NETWORK)
    async with x402HttpxClient(client, timeout=900) as http:
        r = await http.post(f"{endpoint.rstrip('/')}/fix", json={"url": page})
    print("status", r.status_code, "| settlement", r.headers.get("payment-response", "none"))
    body = r.json() if r.content else {}
    report = body.pop("report", None) or {}
    print(json.dumps(body))
    print({k: report.get(k) for k in ("job_id", "violation_count", "error", "note")},
          "fixed:", sum(f["outcome"] == "fixed" for f in report.get("fixes", [])),
          "| signed:", bool(report.get("receipt")))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
